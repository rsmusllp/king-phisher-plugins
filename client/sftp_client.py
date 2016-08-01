import os
import datetime
import stat
import shutil
import threading
import time
import hashlib

from king_phisher import utilities
from king_phisher.client import gui_utilities
from king_phisher.client import plugins

import boltons.strutils
import boltons.timeutils
from gi.repository import Gtk
from gi.repository import Gdk
from gi.repository import GdkPixbuf
from gi.repository import GObject
from gi.repository import GLib
import paramiko

GTYPE_LONG = GObject.type_from_name('glong')
gtk_builder_file = os.path.splitext(__file__)[0] + '.ui'

def get_treeview_column(name, renderer, m_col, m_col_sort=None):
	tv_col = Gtk.TreeViewColumn(name)
	tv_col.pack_start(renderer, True)
	tv_col.add_attribute(renderer, 'text', m_col)
	if m_col_sort is not None:
		tv_col.set_sort_column_id(m_col_sort)
	return tv_col

class Plugin(plugins.ClientPlugin):
	authors = ['Josh Jacob', 'Spencer McIntyre']
	title = 'SFTP Client'
	description = """
	Secure File Transfer Protocol Client that can be used to upload, download,
	create, and delete local and remote files on the King Phisher Server.
	"""
	homepage = 'https://github.com/securestate/king-phisher'
	def initialize(self):
		self.sftp_window = None
		if not os.access(gtk_builder_file, os.R_OK):
			gui_utilities.show_dialog_error(
				'Plugin Error',
				self.application.get_active_window(),
				'The GTK Builder data file (.ui extension) is not available.'
			)
			return
		self.signal_connect('sftp-client-start', self.signal_sftp_start)
		return True

	def finalize(self):
		if self.sftp_window is not None:
			self.sftp_window.destroy()

	def signal_sftp_start(self, _):
		GObject.signal_stop_emission_by_name(self.application, 'sftp-client-start')
		if self.sftp_window is None:
			connection = self.application._ssh_forwarder
			if connection is None:
				message = 'The King Phisher client does not have an active SSH connection\n'
				message += 'to the server. The SFTP client plugin can not be used.'
				gui_utilities.show_dialog_error(
					'No SSH Connection',
					self.application.get_active_window(),
					message
				)
				return
			ssh = connection.client
			self.logger.debug('loading gtk builder file from: ' + gtk_builder_file)
			try:
				manager = FileManager(self.application, ssh)
			except paramiko.ssh_exception.ChannelException as error:
				if len(error.args) == 2:
					details = "SSH Channel Exception #{0} ({1})".format(*error.args)
				else:
					details = 'An unknown SSH Channel Exception occurred.'
				gui_utilities.show_dialog_error(
					'SSH Channel Exception',
					self.application.get_active_window(),
					details
				)
				return
			self.sftp_window = manager.window
			self.sftp_window.connect('destroy', self.signal_window_destroy)
		self.sftp_window.show()
		self.sftp_window.present()

	def signal_window_destroy(self, window):
		self.sftp_window = None

class TaskQueue(object):
	def __init__(self):
		self.mutex = threading.RLock()
		self.not_empty = threading.Condition(self.mutex)
		self.not_full = threading.Condition(self.mutex)
		self.queue = []
		self.unfinished_tasks = 0

	@property
	def queue_ready(self):
		for task in self.queue:
			if task.is_ready:
				yield task

	def _qsize(self, len=len):  # pylint: disable=redefined-builtin
		return len(list(self.queue))

	def _qsize_ready(self, len=len):  # pylint: disable=redefined-builtin
		return len(list(self.queue_ready))

	def get(self, block=True, timeout=None):
		self.not_empty.acquire()
		try:
			if not block:
				if not self._qsize_ready():
					return None
			elif timeout is None:
				while not self._qsize_ready():
					self.not_empty.wait()
			elif timeout < 0:
				raise ValueError("'timeout' must be a non-negative number")
			else:
				endtime = time() + timeout  # pylint: disable = not-callable
				while not self._qsize_ready():
					remaining = endtime - time()  # pylint: disable = not-callable
					if remaining <= 0.0:
						return None
					self.not_empty.wait(remaining)
			task = next(self.queue_ready)
			task.state = 'Active'
			self.not_full.notify()
			return task
		finally:
			self.not_empty.release()

	def put(self, task):
		if not isinstance(task, Task):
			raise TypeError('argument 1 task must be Task instance')
		with self.not_full:
			task.register(self.not_empty)
			self.queue.append(task)
			self.unfinished_tasks += 1
			self.not_empty.notify()

	def remove(self, task):
		with self.mutex:
			self.queue.remove(task)
			self.unfinished_tasks += 1
			self.not_full.notify()

class Task(object):
	_states = ('Active', 'Cancelled', 'Completed', 'Error', 'Paused', 'Pending')
	_ready_states = ('Pending',)
	__slots__ = ('_ready', '_state')
	def __init__(self, state=None):
		self._ready = None
		self._state = None
		self.state = (state or 'Pending')

	@property
	def is_done(self):
		return self._state in ('Cancelled', 'Completed', 'Error')

	@property
	def is_ready(self):
		return self._state in self._ready_states

	@property
	def state(self):
		return self._state

	@state.setter
	def state(self, value):
		if value not in self._states:
			raise ValueError('invalid state')
		self._state = value
		if self._state in self._ready_states and self._ready is not None:
			self._ready.notify()

	def register(self, ready_event):
		if self._ready is not None:
			raise RuntimeError('this task has already been registered')
		self._ready = ready_event

class ShutdownTask(Task):
	pass

class TransferTask(Task):
	_states = ('Active', 'Cancelled', 'Completed', 'Error', 'Paused', 'Pending', 'Transferring')
	__slots__ = ('_state', 'local_path', 'remote_path', 'size', 'transferred', 'treerowref', 'parents', 'init_size')
	def __init__(self, local_path, remote_path, parents=None, state=None):
		super(TransferTask, self).__init__(state=state)
		self.local_path = local_path
		self.remote_path = remote_path
		self.transferred = 0
		self.size = None
		self.treerowref = None
		self.parents = parents
		self.init_size = None

	@property
	def progress(self):
		if self.size is None:
			percent = 0
		elif self.size == 0 and self.transferred == 0:
			percent = 1
		else:
			percent = (float(self.transferred) / float(self.size))
		return min(int(percent * 100), 100)

class DownloadTask(TransferTask):
	transfer_direction = 'download'

class UploadTask(TransferTask):
	transfer_direction = 'upload'

class TransferDirectoryTask(TransferTask):
	has_children = False
	folder_clicked = False

class DownloadDirectoryTask(DownloadTask, TransferDirectoryTask):
	pass

class UploadDirectoryTask(UploadTask, TransferDirectoryTask):
	pass

class StatusDisplay(object):
	def __init__(self, builder, queue):
		self.builder = builder
		self.queue = queue
		self.scroll = self.builder.get_object('logger_scroll')
		self.treeview_transfer = self.builder.get_object('SFTPClientGUI.treeview_transfer')
		self._tv_lock = threading.RLock()
		gsrc_id = GLib.timeout_add(250, self._sync_view, priority=GLib.PRIORITY_DEFAULT_IDLE)  # 250 milliseconds
		self.treeview_transfer.connect('destroy', self.signal_tv_destroy, gsrc_id)
		self.progress_bar = self.builder.get_object('SFTPClientGUI.progressbar')
		self.label_file = self.builder.get_object('SFTPClientGUI.label')


		col_text = Gtk.CellRendererText()
		col_img = Gtk.CellRendererPixbuf()
		col = Gtk.TreeViewColumn('Direction')
		col.pack_start(col_img, False)
		col.add_attribute(col_img, 'pixbuf', 0)
		self.treeview_transfer.append_column(col)

		self.treeview_transfer.append_column(get_treeview_column('Local File', col_text, 1, m_col_sort=1))
		self.treeview_transfer.append_column(get_treeview_column('Remote File', col_text, 2, m_col_sort=2))
		self.treeview_transfer.append_column(get_treeview_column('Status', col_text, 3, m_col_sort=3))

		col_bar = Gtk.TreeViewColumn('Progress')
		progress = Gtk.CellRendererProgress()
		col_bar.pack_start(progress, True)
		col_bar.add_attribute(progress, 'value', 4)
		self.treeview_transfer.append_column(col_bar)

		self.treeview_transfer.append_column(get_treeview_column('Size', col_text, 5, m_col_sort=3))


		self._tv_model = Gtk.TreeStore(GdkPixbuf.Pixbuf, str, str, str, int, str)
		self.treeview_transfer.connect('size-allocate', self.signal_tv_size_allocate)
		self.treeview_transfer.connect('button_press_event', self.signal_tv_button_pressed)
		self.treeview_transfer.set_model(self._tv_model)
		self.treeview_transfer.show_all()

		self.popup_menu = Gtk.Menu.new()

		self.menu_item_paused = Gtk.CheckMenuItem.new_with_label('Paused')
		menu_item = self.menu_item_paused
		menu_item.connect('toggled', self.signal_menu_toggled_paused)
		self.popup_menu.append(menu_item)

		self.menu_item_cancel = Gtk.MenuItem.new_with_label('Cancel')
		menu_item = self.menu_item_cancel
		menu_item.connect('activate', self.signal_menu_activate_cancel)
		self.popup_menu.append(menu_item)

		menu_item = Gtk.SeparatorMenuItem()
		self.popup_menu.append(menu_item)

		menu_item = Gtk.MenuItem.new_with_label('Clear')
		menu_item.connect('activate', self.signal_menu_activate_clear)
		self.popup_menu.append(menu_item)
		self.popup_menu.show_all()

	def _get_selected_tasks(self):
		treepaths = self._get_selected_treepaths()
		return [task for task in self.queue.queue if task.treerowref.valid() and task.treerowref.get_path() in treepaths]

	def _get_selected_treepaths(self):
		selection = self.treeview_transfer.get_selection()
		model, treeiter = selection.get_selected()
		treepaths = []
		treepaths.append(model.get_path(treeiter))
		if model.iter_has_child(treeiter):
			treeiter = model.iter_children(treeiter)
			self._get_rows(model, treeiter, treepaths)
		return treepaths

	def _get_rows(self, model, treeiter, treepaths):
		while treeiter is not None:
			treepaths.append(model.get_path(treeiter))
			if model.iter_has_child(treeiter):
				childiter = model.iter_children(treeiter)
				self._get_rows(model, childiter, treepaths)
			treeiter = model.iter_next(treeiter)


	def _change_task_state(self, state_from, state_to):
		with self.queue.mutex:
			for task in self._get_selected_tasks():
				if task.state in state_from:
					if state_to == 'Cancelled':
						if isinstance(task, TransferDirectoryTask):
							if task.has_children:
								task.folder_clicked = True
						elif task.parents is not None:
							for parent in task.parents:
								if not parent.folder_clicked:
									parent.size -= 1
					task.state = state_to

	def _sync_view(self):
		if not self.queue.mutex.acquire(blocking=False):
			return
		if not self._tv_lock.acquire(blocking=False):
			self.queue.mutex.release()
			return
		for task in self.queue.queue:
			parent_treerowref = None
			if task.parents is not None:
				parent_treerowref = task.parents[len(task.parents)-1].treerowref
				if parent_treerowref is None:
					self.queue.queue.remove(task)
					continue
				parent_path = parent_treerowref.get_path()
				if parent_path is None:
					self.queue.queue.remove(task)
					continue
				parent_treerowref = self._tv_model.get_iter(parent_path)
			if not isinstance(task, TransferTask):
				continue
			if task.treerowref is None:
				stock = Gtk.STOCK_GO_FORWARD if task.transfer_direction == 'upload' else Gtk.STOCK_GO_BACK
				image = self.treeview_transfer.render_icon(stock, Gtk.IconSize.BUTTON, None) if parent_treerowref is None else Gtk.Image()
				treeiter = self._tv_model.append(parent_treerowref, [
					image,
					task.local_path,
					task.remote_path,
					task.state,
					0,
					boltons.strutils.bytes2human(task.init_size) if task.init_size is not None else None
				])
				task.treerowref = Gtk.TreeRowReference(self._tv_model, self._tv_model.get_path(treeiter))
			elif task.treerowref.valid():
				row = self._tv_model[task.treerowref.get_path()]  # pylint: disable=unsubscriptable-object
				row[3] = task.state
				row[4] = task.progress
		self.queue.mutex.release()
		return True

	def signal_menu_activate_clear(self, _):
		with self.queue.mutex:
			for task in self.queue.queue:
				if not task.is_done:
					continue
				if task.treerowref is not None and task.treerowref.valid():
					self._tv_model.remove(self._tv_model.get_iter(task.treerowref.get_path()))
					task.treerowref = None
				self.queue.queue.remove(task)
			self.queue.not_full.notify()

	def signal_menu_toggled_paused(self, _):
		if self.menu_item_paused.get_active():
			self._change_task_state(('Active', 'Pending', 'Transferring'), 'Paused')
		else:
			self._change_task_state(('Paused',), 'Pending')

	def signal_menu_activate_cancel(self, _):
		self._change_task_state(('Active', 'Paused', 'Pending', 'Transferring'), 'Cancelled')

	def signal_tv_button_pressed(self, _, event):
		if event.button == Gdk.BUTTON_SECONDARY:
			selected_tasks = self._get_selected_tasks()
			if not selected_tasks:
				self.menu_item_cancel.set_sensitive(False)
				self.menu_item_paused.set_sensitive(False)
			else:
				self.menu_item_cancel.set_sensitive(True)
				self.menu_item_paused.set_sensitive(True)
				tasks_are_paused = [task.state == 'Paused' for task in selected_tasks]
				if any(tasks_are_paused):
					self.menu_item_paused.set_active(True)
					self.menu_item_paused.set_inconsistent(not all(tasks_are_paused))
				else:
					self.menu_item_paused.set_active(False)
					self.menu_item_paused.set_inconsistent(False)
			self.popup_menu.popup(None, None, None, None, event.button, Gtk.get_current_event_time())
			return True
		return

	def signal_tv_destroy(self, _, gsrc_id):
		self._tv_lock.acquire()
		GLib.source_remove(gsrc_id)
		# purposely don't release self._tv_lock, the tv has been destroyed

	def signal_tv_size_allocate(self, _, event, data=None):
		adj = self.scroll.get_vadjustment()
		adj.set_value(0)

class DirectoryBase(object):
	def __init__(self, builder, application, default_directory):
		self.application = application
		self.treeview = builder.get_object('SFTPClientGUI.' + self.treeview_name)
		self.default_directory = default_directory
		self.col_name = Gtk.CellRendererText()
		self.col_name.connect('edited', self.signal_text_edited)
		col_text = Gtk.CellRendererText()
		col_img = Gtk.CellRendererPixbuf()

		col = Gtk.TreeViewColumn('Files')
		col.pack_start(col_img, False)
		col.pack_start(self.col_name, True)
		col.add_attribute(self.col_name, 'text', 0)
		col.add_attribute(col_img, 'pixbuf', 1)
		col.set_sort_column_id(0)

		self.treeview.append_column(col)
		self.treeview.append_column(get_treeview_column('Permissions', col_text, 3, m_col_sort=3))
		self.treeview.append_column(get_treeview_column('Size', col_text, 4, m_col_sort=5))
		self.treeview.append_column(get_treeview_column('Date Modified', col_text, 6, m_col_sort=6))

		self.treeview.connect('button_press_event', self.signal_tv_button_press)
		self.treeview.connect('key-press-event', self.signal_tv_key_press)
		self.treeview.connect('row-expanded', self.signal_tv_expand_row)
		self.treeview.connect('row-collapsed', self.signal_tv_collapse_row)
		self._tv_model = Gtk.TreeStore(str, GdkPixbuf.Pixbuf, str, str, str, GTYPE_LONG, str)
		tree_filter = self._tv_model.filter_new()
		tree_filter.set_visible_func(self.show_hidden_files)
		self.treeview.set_model(self._tv_model)

		self.local_hidden = True
		self._get_popup_menu()
		self.load_dirs(default_directory)

	def _delete_selection(self):
		selection = self.treeview.get_selection()
		model, treeiter = selection.get_selected()
		confirmed = gui_utilities.show_dialog_yes_no(
			'Confirm Delete',
			self.application.get_active_window(),
			"Are you sure you want to delete the selected {0}?".format('directory' if model[treeiter][5] == -1 else 'file')
		)
		if confirmed:
			self.delete(model, treeiter)

	def _get_popup_menu(self):
		self.popup_menu = Gtk.Menu.new()
		menu_item = Gtk.CheckMenuItem.new_with_label('Show Hidden Files')
		menu_item.connect('toggled', self.signal_menu_toggled_hidden_files)
		self.signal_menu_toggled_hidden_files = menu_item
		self.popup_menu.append(menu_item)

		self.menu_item_transfer = Gtk.MenuItem.new_with_label(self.transfer_direction.title())
		self.popup_menu.append(self.menu_item_transfer)

		menu_item = Gtk.MenuItem.new_with_label('Collapse All')
		menu_item.connect('activate', self.signal_menu_activate_collapse_all)
		self.popup_menu.append(menu_item)

		menu_item = Gtk.MenuItem.new_with_label('Create Folder')
		menu_item.connect('activate', self.signal_menu_activate_create_folder)
		self.popup_menu.append(menu_item)

		menu_item = Gtk.MenuItem.new_with_label('Rename')
		menu_item.connect('activate', self.signal_menu_activate_rename)
		self.popup_menu.append(menu_item)

		menu_item = Gtk.SeparatorMenuItem()
		self.popup_menu.append(menu_item)

		menu_item = Gtk.MenuItem.new_with_label('Delete')
		menu_item.connect('activate', self.signal_menu_activate_delete_prompt)
		self.popup_menu.append(menu_item)

		self.popup_menu.show_all()

	def _rename_selection(self):
		selection = self.treeview.get_selection()
		_, treeiter = selection.get_selected()
		self.rename(treeiter)

	def get_is_folder(self, fullname):
		return stat.S_ISDIR(self.stat(fullname).st_mode)

	def get_file_size(self, fullname):
		return self.stat(fullname).st_size

	def signal_tv_button_press(self, _, event):
		if event.button == Gdk.BUTTON_SECONDARY:
			self.popup_menu.popup(None, None, None, None, event.button, Gtk.get_current_event_time())
			return True
		return

	def signal_tv_key_press(self, treeview, event):
		if event.type != Gdk.EventType.KEY_PRESS:
			return
		keyval = event.get_keyval()[1]
		if keyval == Gdk.KEY_F2:
			self._rename_selection()
		elif keyval == Gdk.KEY_F5:
			self.refresh()
		elif keyval == Gdk.KEY_Delete:
			self._delete_selection()

	def rename(self, treeiter):
		path = self._tv_model.get_path(treeiter)
		fullname = self._tv_model[path][2]
		parent = self._tv_model.iter_parent(treeiter)
		if parent is None:
			parent_name = self.default_directory
		else:
			parent_name = self._tv_model[parent][2]
		if self._tv_model[treeiter][2] is not None:
			perm = self._check_perm(parent_name)
			w_perm = True if perm[4] == 'w' else False
			if not w_perm:
				gui_utilities.show_dialog_error('Permission Denied', self.application.get_active_window(), "Cannot access {0} as user".format(fullname))
				return
		col = self.treeview.get_column(0)
		self.col_name.set_property('editable', True)
		self.treeview.set_cursor(path, col, True)
		self.col_name.set_property('editable', False)

	def signal_menu_activate_rename(self, _):
		self._rename_selection()

	def signal_tv_collapse_row(self, _, treeiter, treepath):
		current = self._tv_model.iter_children(treeiter)
		while current:
			self._tv_model.remove(current)
			current = self._tv_model.iter_children(treeiter)
		self._tv_model.append(treeiter, [None, None, None, None, None, None, None])

	def signal_tv_expand_row(self, _, treeiter, treepath):
		new_path = self._tv_model[treeiter][2]  # pylint: disable=unsubscriptable-object
		self.load_dirs(new_path, treeiter)
		self._tv_model.remove(self._tv_model.iter_children(treeiter))

	def load_dirs(self, path, parent=None):
		for name in self._yield_dir_list(path):
			if self.local_hidden and name.startswith('.'):
				continue
			if path.endswith('/'):
				fullname = path + name
			else:
				fullname = path + '/' + name
			try:
				perm = self._check_perm(fullname)
				raw_time = self._get_raw_time(fullname)
				date = datetime.datetime.fromtimestamp(raw_time)
				date_modified = '   ' + utilities.format_datetime(date)
				is_folder = self.get_is_folder(fullname)
			except (OSError, IOError):
				icon = Gtk.IconTheme.get_default().load_icon('emblem-unreadable', 13, 0)
				self._tv_model.append(parent, [name, icon, fullname, None, None, None, None])
				continue
			if is_folder:
				icon = Gtk.IconTheme.get_default().load_icon('folder', 20, 0)
				current = self._tv_model.append(parent, (name, icon, fullname, perm, None, -1, date_modified))
			else:
				file_size = self.get_file_size(fullname)
				hr_file_size = '   ' + boltons.strutils.bytes2human(file_size)
				icon = Gtk.IconTheme.get_default().load_icon('text-x-preview', 12.5, 0)
				current = self._tv_model.append(parent, (name, icon, fullname, perm, hr_file_size, file_size, date_modified))
			if is_folder and perm[3] == 'r' and perm[5] == 'x':
				self._tv_model.append(current, [None, None, None, None, None, None, None])

	def signal_menu_toggled_hidden_files(self, _):  # pylint: disable=method-hidden
		self.local_hidden = not self.local_hidden
		self.refresh()

	def show_hidden_files(self, model, _iter, data):
		#print self._tv_model[_iter:1]
		pass

	def signal_menu_activate_collapse_all(self, _):
		self.treeview.collapse_all()

	def refresh(self):
		model = self._tv_model
		exp_lines = []
		model.foreach(lambda model, path, iter: exp_lines.append(path) if self.treeview.row_expanded(path) else 0)
		self.treeview.collapse_all()
		for path in exp_lines:
			self.treeview.expand_row(path, False)

	def signal_menu_activate_create_folder(self, _):
		selection = self.treeview.get_selection()
		model, treeiter = selection.get_selected()
		if treeiter is not None:
			fullname = model[treeiter][2]
			path = self._tv_model.get_path(treeiter)
		else:
			fullname = self.default_directory
		perm = self._check_perm(fullname)
		w_perm = True if perm[4] == 'w' else False
		if not w_perm:
			gui_utilities.show_dialog_error('Permission Denied', self.application.get_active_window(), "Cannot access {0} as user".format(fullname))
			return
		if treeiter is None:
			current = self._tv_model.append(treeiter, [' ', None, None, None, None, None, None])
			self.rename(current)
			return
		if not self.treeview.row_expanded(path):
			self.treeview.expand_row(path, False)
		if self._tv_model.iter_children(treeiter) is None:
			self._tv_model.append(treeiter, [None, None, None, None, None, None, None])
			current = self._tv_model.append(treeiter, [' ', None, None, None, None, None, None])
			self.treeview.expand_row(path, False)
		else:
			current = self._tv_model.append(treeiter, [' ', None, None, None, None, None, None])
		self.rename(current)

	def signal_text_edited(self, renderer, path, text):
		_iter = self._tv_model.get_iter(path)
		parent = self._tv_model.iter_parent(_iter)
		if parent is None:
			new_path = self.default_directory + '/' + text
		else:
			new_path = self._tv_model[parent][2] + '/' + text
		if text == ' ' or text == self._tv_model[_iter][0]:
			self.refresh()
			return
		if self._already_exists(new_path):
			gui_utilities.show_dialog_error('Unable to make directory', self.application.get_active_window(), "Directory: {0} already exists".format(new_path))
			self.refresh()
			return
		if self._tv_model[_iter][2] is not None:
			self._rename_file(_iter, new_path)
		else:
			self._tv_model.remove(_iter)
			self._make_file(new_path)
		self.refresh()

	def signal_menu_activate_delete_prompt(self, _):
		self._delete_selection()

def handle_permission_denied(function, *args, **kwargs):
	def wrapper(self, *args, **kwargs):
		try:
			func = function(self, *args, **kwargs)
		except (IOError, OSError) as error:
			err_type = error[0]
			print error
			print (function, args, kwargs)
			err_message = 'An undocumented error occured'
			gui_utilities.show_dialog_error(
				'Permission Denied',
				self.application.get_active_window(),
				err_message
			)
			return False
		else:
			return True
	return wrapper

class LocalDirectory(DirectoryBase):
	transfer_direction = 'upload'
	treeview_name = 'treeview_local'
	def __init__(self, builder, application):
		self.stat = os.stat
		super(LocalDirectory, self).__init__(builder, application, os.path.abspath(os.sep))

	def _check_perm(self, fullname):
		perm = '   '
		perm = perm + 'r' if os.access(fullname, os.R_OK) else perm + '-'
		perm = perm + 'w' if os.access(fullname, os.W_OK) else perm + '-'
		perm = perm + 'x' if os.access(fullname, os.X_OK) else perm + '-'
		return perm

	def _yield_dir_list(self, path):
		for name in os.listdir(path):
			yield name

	def _already_exists(self, path):
		return os.path.isdir(path)
	
	def _already_exists_all(self, path):
		return os.path.exists(path)

	def _rename_file(self, _iter, path):
		os.rename(self._tv_model[_iter][2], path)  # pylint: disable=unsubscriptable-object

	@handle_permission_denied
	def _make_file(self, path):
		os.makedirs(path)

	def _get_raw_time(self, fullname):
		return os.path.getmtime(fullname)

	@handle_permission_denied
	def delete(self, model, treeiter):
		if model[treeiter][5] == -1:
			shutil.rmtree(model[treeiter][2])
		else:
			os.remove(model[treeiter][2])
		gui_utilities.show_dialog_warning('Successfully deleted ' + model[treeiter][2], self.application.get_active_window())
		self.refresh()

	@handle_permission_denied
	def remove_by_folder_name(self, name):
		shutil.rmtree(name)

	@handle_permission_denied
	def remove_by_file_name(self, name):
		os.remove(name)

	def walk(self, src_file, src, commands, local_name, old_files):
		for walker in os.walk(src_file):
			walker = list(walker)
			temp = walker[0].split('/')
			loc = temp.index(local_name)
			parsed_name = '/'.join(temp[loc:])
			old_files[parsed_name] = walker[0]
			walker[0] = parsed_name
			commands.append(walker)

class RemoteDirectory(DirectoryBase):
	transfer_direction = 'download'
	treeview_name = 'treeview_remote'
	def __init__(self, builder, application, ftp):
		self.ftp = ftp
		self.stat = ftp.stat
		super(RemoteDirectory, self).__init__(builder, application, application.config['server_config']['server.web_root'])

	def _check_perm(self, fullname):
		mode = self.ftp.stat(fullname).st_mode
		readable = True
		writable = True
		'''
		try:
			_file = self.ftp.open(fullname)
		except IOError:
			pass
		else:
			readable = True
			_file.close()
		if not self.get_is_folder(fullname):
			try:
				_file = self.ftp.open(fullname, 'w')
			except IOError:
				pass
			else:
				writable = True
				_file.close()
		else:
			temp_name = '.abcdefg'
			path = os.path.join(fullname, temp_name)
			try:
				_file = self.ftp.open(path, 'w+')
			except IOError:
				pass
			else:
				writable = True
				_file.close()
				self.remove_by_file_name(path)
		'''
		perm = '   '
		perm += 'r' if readable else '-'
		perm += 'w' if writable else '-'
		perm += 'x' if bool(mode & stat.S_IXOTH) else '-'
		return perm

	def _yield_dir_list(self, path):
		for name in self.ftp.listdir(path):
			yield name

	def _already_exists(self, path):
		try:
			self.ftp.stat(path)
		except IOError as error:
			if error[0] == 2:
				return False
		else:
			return True

	def _rename_file(self, _iter, path):
		self.ftp.rename(self._tv_model[_iter][2], path)  #pylint: disable=unsubscriptable-object

	@handle_permission_denied
	def _make_file(self, path):
		self.ftp.mkdir(path)

	def _get_raw_time(self, fullname):
		lstatout = self.ftp.stat(fullname)
		return lstatout.st_mtime

	@handle_permission_denied
	def delete(self, model, treeiter):
		if self.get_is_folder(self._tv_model[treeiter][2]):  #pylint: disable=unsubscriptable-object
			print model[treeiter][2]
			self.ftp.rmdir(model[treeiter][2])
		else:
			self.ftp.remove(model[treeiter][2])
		gui_utilities.show_dialog_warning('Successfully deleted ' + model[treeiter][2], self.application.get_active_window())
		self.refresh()

	@handle_permission_denied
	def remove_by_folder_name(self, name):
		return True

	@handle_permission_denied
	def remove_by_file_name(self, name):
		self.ftp.remove(name)

	def walk(self, _dir, src, commands, remote_name, old_files):
		subdirs = []
		files = []
		temp = _dir.split('/')
		loc = temp.index(remote_name)
		parsed_name = '/'.join(temp[loc:])
		for f in src._yield_dir_list(_dir):
			if src.get_is_folder(_dir + '/' + f):
				subdirs.append(f)
			else:
				files.append(f)
		command = [parsed_name, subdirs, files]
		commands.append(command)
		old_files[parsed_name] = _dir
		for folder in subdirs:
			new_path = os.path.join(_dir, folder)
			self.walk(new_path, src, commands, remote_name, old_files)

	def _already_exists_all(self, path):
		return True

class FileManager(object):
	def __init__(self, application, ssh):
		self.ssh = ssh
		self.application = application
		self.queue = TaskQueue()
		self._threads = []
		self._threads_max = 1
		self._threads_shutdown = threading.Event()
		for _ in range(self._threads_max):
			thread = threading.Thread(target=self._thread_routine, args=(ssh,))
			thread.start()
			self._threads.append(thread)
		ftp = ssh.open_sftp()
		self.ftp = ftp
		self.builder = Gtk.Builder()
		self.builder.add_from_file(gtk_builder_file)
		self.window = self.builder.get_object('SFTPClientGUI.window')
		self.menubar = self.builder.get_object('SFTPClientGUI.menu')
		self.render_menubar(self.menubar)
		self.status_display = StatusDisplay(self.builder, self.queue)
		self.local = LocalDirectory(self.builder, self.application)
		self.remote = RemoteDirectory(self.builder, self.application, ftp)
		self.builder.get_object('button_upload').connect('button-press-event', lambda widget, event: self._queue_transfer(UploadTask))
		self.builder.get_object('button_download').connect('button-press-event', lambda widget, event: self._queue_transfer(DownloadTask))
		self.local.menu_item_transfer.connect('activate', lambda widget: self._queue_transfer(UploadTask))
		self.remote.menu_item_transfer.connect('activate', lambda widget: self._queue_transfer(DownloadTask))
		self.window.connect('destroy', self.signal_window_destroy)
		self.window.show_all()

	def render_menubar(self, menubar):
		self.validate = False
		menu_item = Gtk.CheckMenuItem.new_with_label('Checksum Validation')
		menu_item.connect('toggled', self.validate_checksums)
		self.validate_checksums = menu_item
		menubar.append(menu_item)

		menu_item = Gtk.CheckMenuItem.new_with_label('Transfer Hidden Files')
		menu_item.connect('toggled', self.transfer_hidden)
		self.transfer_hidden = menu_item
		menubar.append(menu_item)

		menu_item = Gtk.SeparatorMenuItem()
		menubar.append(menu_item)

		menu_item = Gtk.MenuItem.new_with_label('Exit')
		menu_item.connect('activate', self.shutdown)
		menubar.append(menu_item)

	def shutdown(self, _):
		pass

	def transfer_hidden(self, _):
		pass

	def validate_checksums(self, _):
		self.validate = not self.validate

	def _transfer_folder(self, task, ssh):
		task.state = 'Transferring'
		if isinstance(task, UploadTask):
			self.remote._make_file(task.remote_path)
		elif isinstance(task, DownloadTask):
			self.local._make_file(task.local_path)
		if task.size is None:
			task.transferred = 0
			task.size = 0
			task.state = 'Completed'

	def _transfer(self, task, ssh, chunk=0x1000):
		task.state = 'Transferring'
		ftp = ssh.open_sftp()
		write_mode = 'ab+' if task.transferred > 0 else 'wb+'
		try:
			if isinstance(task, UploadTask):
				task.size = self.local.get_file_size(task.local_path)
				src_file_h = open(task.local_path, 'rb')
				dst_file_h = ftp.file(task.remote_path, write_mode)
			elif isinstance(task, DownloadTask):
				task.size = self.remote.get_file_size(task.remote_path)
				src_file_h = ftp.file(task.remote_path, 'rb')
				dst_file_h = open(task.local_path, write_mode)
			else:
				raise ValueError('unsupported task type passed to _transfer')
			src_file_h.seek(task.transferred)
			while task.transferred < task.size:
				if self._threads_shutdown.is_set():
					task.state = 'Cancelled'
				if task.state != 'Transferring':
					if task.state == 'Cancelled':
						if isinstance(task, UploadTask):
							self.remote.remove_by_file_name(task.remote_path)
						elif isinstance(task, DownloadTask):
							self.local.remove_by_file_name(task.local_path)
					break
				temp = src_file_h.read(chunk)
				dst_file_h.write(temp)
				task.transferred += chunk
			else:
				task.state = 'Completed'
				if self.validate:
					src_file_h.seek(0)
					dst_file_h.seek(0)
					src_hash = hashlib.md5(src_file_h.read()).hexdigest()
					dst_hash = hashlib.md5(dst_file_h.read()).hexdigest()
					if src_hash == dst_hash:
						self.application.logger.info("{0} and {1} have been validated".format(task.local_path, task.remote_path))
					else:
						self.application.logger.error("{0} and {1} were not properly transferred".format(task.local_path, task.remote_path))
				if task.parents is not None:
					for parent in task.parents:
						parent.transferred += 1
						if parent.transferred >= parent.size:
							parent.state = 'Completed'
				GLib.idle_add(self._idle_refresh_directories)
			src_file_h.close()
			dst_file_h.close()
		except:  # pylint: disable=bare-except
			if not task.is_done:
				self.application.logger.error("Error transferring {0} to {1}".format('a', 'b'))
				task.state = 'Error'
				if task.parents is not None:
					for parent in task.parents:
						parent.state = 'Error'
		finally:
			ftp.close()

	def _idle_refresh_directories(self):
		self.local.refresh()
		self.remote.refresh()

	def _thread_routine(self, ssh):
		while not self._threads_shutdown.is_set():
			task = self.queue.get()
			if isinstance(task, ShutdownTask):
				task.state = 'Completed'
				self.queue.remove(task)
				break
			elif isinstance(task, TransferTask):
				if isinstance(task, TransferDirectoryTask):
					self._transfer_folder(task, ssh)
				else:
					self._transfer(task, ssh)

	def signal_window_destroy(self, _):
		self.ftp.close()
		self.window.set_sensitive(False)
		self._threads_shutdown.set()
		for _ in self._threads:
			self.queue.put(ShutdownTask())
		for thread in self._threads:
			thread.join()

	def _queue_transfer(self, task_cls):
		selection = self.local.treeview.get_selection()
		model, treeiter = selection.get_selected()
		if treeiter is None:
			local_file = self.local.default_directory
			local_name = self.local.default_directory
		else:
			local_file = model[treeiter][2]
			local_name = model[treeiter][0]

		selection = self.remote.treeview.get_selection()
		model, treeiter = selection.get_selected()
		if treeiter is None:
			remote_file = self.remote.default_directory
			remote_name = self.remote.default_directory
		else:
			remote_file = model[treeiter][2]
			remote_name = model[treeiter][0]

		if issubclass(task_cls, DownloadTask):
			src, dst = self.remote, self.local
			src_file, dst_file = remote_file, local_file
		elif issubclass(task_cls, UploadTask):
			src, dst = self.local, self.remote
			src_file, dst_file = local_file, remote_file
		else:
			raise ValueError('task_cls must be a subclass of TransferTask')

		if dst.get_is_folder(dst_file):
			dst_dir = dst_file
			dst_file = os.path.join(dst_file, os.path.basename(src_file))
		else:
			gui_utilities.show_dialog_error(
				'Error',
				self.application.get_active_window(),
				'Not a valid destination.'
			)
			return

		if src.get_is_folder(src_file):
			self.handle_folder_transfer(task_cls, remote_name, local_name, src, dst, src_file, dst_file, dst_dir, remote_file, local_file)
		else:
			self.handle_file_transfer(task_cls, local_file, src_file, dst_file, dst_dir)

	def handle_file_transfer(self, task_cls, local_file, src_file, dst_file, dst_dir):
		if issubclass(task_cls, DownloadTask):
			if not os.access(dst_dir, os.W_OK):
				gui_utilities.show_dialog_error(
					'Permission Denied',
					self.application.get_active_window(),
					'Cannot write to the destination folder.'
				)
				return
			local_file, remote_file = dst_file, src_file
		elif issubclass(task_cls, UploadTask):
			if not os.access(local_file, os.R_OK):
				gui_utilities.show_dialog_error(
					'Permission Denied',
					self.application.get_active_window(),
					'Cannot read the source file.'
				)
				return
			local_file, remote_file = src_file, dst_file
		file_task = task_cls(local_file, remote_file)
		if isinstance(file_task, UploadTask):
			file_size = self.local.get_file_size(local_file)
		elif isinstance(file_task, DownloadTask):
			file_size = self.remote.get_file_size(remote_file)
		file_task.init_size = file_size
		self.queue.put(file_task)

	def handle_folder_transfer(self, task_cls, remote_name, local_name, src, dst, src_file, dst_file, dst_dir, remote_file, local_file):
		commands = []
		old_files = {}
		uload = False
		if issubclass(task_cls, UploadTask):
			name = local_name
			uload = True
		elif issubclass(task_cls, DownloadTask):
			name = remote_name
		src.walk(src_file, src, commands, name, old_files)
		parents = []
		for command in commands:
			hidden = False
			new_dir = dst_dir + '/' + command[0]
			old_dir = old_files[command[0]]
			for part in command[0].split('/'):
				if part.startswith('.'):
					hidden = True
					break
			if hidden:
				continue
			if dst._already_exists(new_dir):
				confirmed = gui_utilities.show_dialog_yes_no(
					'Warning',
					self.application.get_active_window(),
					"Folder {0} already exists. Replace?".format(new_dir)
				)
				if not confirmed:
					return
				if not dst.remove_by_folder_name(new_dir):
					return
			if not dst._make_file(new_dir):
				return
			dst.remove_by_folder_name(new_dir)
			temp = command[0].split('/')
			for i in range(0, len(temp)):
				name = '/'.join(temp[0:i+1])
				parent_task = (parents[i-1][0],) if i > 0 else None
				if not uload:
					task = (DownloadDirectoryTask(new_dir, old_dir, parents=parent_task), name)
				else:
					task = (UploadDirectoryTask(old_dir, new_dir, parents=parent_task), name)
				if i >= len(parents):
					parents.append(task)
					self.queue.put(task[0])
				elif name != parents[i][1]:
					parents[i] = task
					self.queue.put(task[0])
			for i in range(0, len(parents) - len(temp)):
				parents.pop()
			for _file in command[2]:
				if _file.startswith('.'):
					continue
				new_file = new_dir + '/' + _file
				old_file = old_files[command[0]] + '/' + _file
				if not src._already_exists_all(old_file):
					self.application.logger.error("{0} is neither a file nor folder".format(old_file))
					continue
				if uload:
					local_file, remote_file = old_file, new_file
				else:
					local_file, remote_file = new_file, old_file
				actual_parents = []
				for parent in parents:
					if parent[0].size is None:
						parent[0].size = 1
					else:
						parent[0].size += 1
					parent[0].has_children = True
					actual_parents.append(parent[0])
				file_task = task_cls(local_file, remote_file, parents=actual_parents)
				if isinstance(file_task, UploadTask):
					file_size = self.local.get_file_size(local_file)
				elif isinstance(file_task, DownloadTask):
					file_size = self.remote.get_file_size(remote_file)
				file_task.init_size = file_size
				self.queue.put(file_task)
