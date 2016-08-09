import datetime
import errno
import hashlib
import logging
import os
import stat
import shutil
import threading
import time

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
PARENT_DIRECTORY = '..'
CURRENT_DIRECTORY = '.'

gtk_builder_file = os.path.splitext(__file__)[0] + '.ui'
logger = logging.getLogger('KingPhisher.Plugins.SFTPClient')

def get_treeview_column(name, renderer, m_col, m_col_sort=None, resizable=False):
	"""
	A function used to generate a generic treeview column.

	:param str name: The name of the column.
	:param renderer: The Gtk renderer to be used for the column.
	:param m_col: The column position in the model.
	:param m_col_sort: The column to sort column data by.
	:param bool resizable: Decide whether the column should be resizable.
	:return: A TreeViewColumn Object with the desired setttings.
	"""
	tv_col = Gtk.TreeViewColumn(name)
	tv_col.pack_start(renderer, True)
	tv_col.add_attribute(renderer, 'text', m_col)
	tv_col.set_property('resizable', resizable)
	if m_col_sort is not None:
		tv_col.set_sort_column_id(m_col_sort)
	return tv_col

def handle_permission_denied(function, *args, **kwargs):
	"""
	Handles Permissions Denied errors when performing actions on files or folders.

	:param function: A function to be tested for IOErrors and OSErrors.
	:return: True if the function did not raise an error and false if it did.
	"""
	def wrapper(self, *args, **kwargs):
		try:
			function(self, *args, **kwargs)
		except (IOError, OSError) as error:
			logger.error('an exception occurred during an operation', exc_info=True)
			err_message = "An error occured: {0}".format(error)
			gui_utilities.show_dialog_error(
				'Error',
				self.application.get_active_window(),
				err_message
			)
			return False
		return True
	return wrapper

class Plugin(plugins.ClientPlugin):
	authors = ['Josh Jacob', 'Spencer McIntyre']
	title = 'SFTP Client'
	description = """
	Secure File Transfer Protocol Client that can be used to upload, download,
	create, and delete local and remote files on the King Phisher Server.
	"""
	homepage = 'https://github.com/securestate/king-phisher'

	def initialize(self):
		"""Connects to the start SFTP Client Signal to the plugin and checks for .ui file."""
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
		"""Allows the window to be properly closed upon the deactivation of the plugin."""
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
	"""
	Task queue used for transfer tasks that handles thread and task management
	in a way to prevent errors.
	"""
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
				raise ValueError('\'timeout\' must be a non-negative number')
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
		"""
		Put a task in the queue.

		:param task: A task to be put in the queue.
		"""
		if not isinstance(task, Task):
			raise TypeError('argument 1 task must be Task instance')
		with self.not_full:
			task.register(self.not_empty)
			self.queue.append(task)
			self.unfinished_tasks += 1
			self.not_empty.notify()

	def remove(self, task):
		"""
		Remove a task from the queue.

		:param task: A task to be removed from the queue.
		"""
		with self.mutex:
			self.queue.remove(task)
			self.unfinished_tasks += 1
			self.not_full.notify()

class Task(object):
	"""
	Generic task class that contains information about task state and readiness.
	"""
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
	"""
	Dummy task used to signal the queue to shutdown.
	"""
	pass

class TransferTask(Task):
	"""
	Task used to model transfers. Each task is put in the queue where it will be
	pass into the _transfer method of the FileManager class for the transfer to
	occur.
	"""
	_states = ('Active', 'Cancelled', 'Completed', 'Error', 'Paused', 'Pending', 'Transferring')
	__slots__ = ('_state', 'local_path', 'remote_path', 'size', 'transferred', 'treerowref', 'parents')
	def __init__(self, local_path, remote_path, parents=None, state=None):
		super(TransferTask, self).__init__(state=state)
		self.local_path = local_path
		"""A string representing the local filesystem path of the transfer."""
		self.remote_path = remote_path
		"""A string representing the remote filesystem path of the transfer."""
		self.transferred = 0
		"""
		If the task is a file transfer, an integer of the number of bytes transferred,
		if the task is a directory transfer, the number of children files transferred.
		"""
		self.size = None
		"""
		If the task is a file transfer, an integer of the total number of bytes,
		if the task is a directory transfer, the total number of children files.
		"""
		self.treerowref = None
		"""A TreeRowReference object representing the Tasks position in the treeview."""
		self.parents = parents or []
		"""A list of TransferDirectoryTasks representing all parent directories of the task."""

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
	"""
	Subclass of TransferTask that indicates
	the task is downloading files.
	"""
	transfer_direction = 'download'

class UploadTask(TransferTask):
	"""
	Subclass of TransferTask that indicates
	the task is uploading files.
	"""
	transfer_direction = 'upload'

class TransferDirectoryTask(TransferTask):
	"""
	Task to model a folder transfer. Acts as a parent task
	to other TransferTasks and is passed into _transfer_folder.
	"""
	has_children = False
	folder_clicked = False
	empty = False

class DownloadDirectoryTask(DownloadTask, TransferDirectoryTask):
	"""
	Subclass of DownloadTask and TransferDirectoryTask that indicates the task
	is downloading folders.
	"""
	pass

class UploadDirectoryTask(UploadTask, TransferDirectoryTask):
	"""
	Subclass of UploadTask and TransferDirectoryTask that indicates the task is
	uploading folders.
	"""
	pass

class StatusDisplay(object):
	"""
	Class representing the bottom treeview of the GUI. This contains the logging
	and graphical representation of all queued transfers. This display is
	updated every 250ms and otherwise only updated with GLib.idle_add.
	"""
	def __init__(self, builder, queue):
		self.builder = builder
		self.queue = queue
		self.scroll = self.builder.get_object('logger_scroll')
		self.treeview_transfer = self.builder.get_object('SFTPClientGUI.treeview_transfer')
		self._tv_lock = threading.RLock()
		gsrc_id = GLib.timeout_add(250, self._sync_view, priority=GLib.PRIORITY_DEFAULT_IDLE)  # 250 milliseconds
		self.treeview_transfer.connect('destroy', self.signal_tv_destroy, gsrc_id)

		col_text = Gtk.CellRendererText()
		col_img = Gtk.CellRendererPixbuf()
		col = Gtk.TreeViewColumn('Direction')
		col.pack_start(col_img, False)
		col.add_attribute(col_img, 'pixbuf', 0)
		self.treeview_transfer.append_column(col)

		self.treeview_transfer.append_column(get_treeview_column('Local File', col_text, 1, m_col_sort=1, resizable=True))
		self.treeview_transfer.append_column(get_treeview_column('Remote File', col_text, 2, m_col_sort=2, resizable=True))
		self.treeview_transfer.append_column(get_treeview_column('Status', col_text, 3, m_col_sort=3, resizable=True))

		col_bar = Gtk.TreeViewColumn('Progress')
		progress = Gtk.CellRendererProgress()
		col_bar.pack_start(progress, True)
		col_bar.add_attribute(progress, 'value', 4)
		col_bar.set_property('resizable', True)
		self.treeview_transfer.append_column(col_bar)

		self.treeview_transfer.append_column(get_treeview_column('Size', col_text, 5, m_col_sort=3, resizable=True))
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
		if treepaths is None:
			return None
		# Find the task selected task then find tall the tasks in the queue with it as a parent.
		parent_task = [task for task in self.queue.queue if task.treerowref is not None and task.treerowref.valid() and task.treerowref.get_path() in treepaths][0]
		children = [task for task in self.queue.queue if parent_task in task.parents]
		children.insert(0, parent_task)
		return children

	def _get_selected_treepaths(self):
		selection = self.treeview_transfer.get_selection()
		model, treeiter = selection.get_selected()
		if treeiter is None:
			return None
		treepaths = []
		treepaths.append(model.get_path(treeiter))
		return treepaths

	def _change_task_state(self, state_from, state_to):
		with self.queue.mutex:
			for task in self._get_selected_tasks():
				if task.state not in state_from:
					continue
				if state_to == 'Cancelled':
					if isinstance(task, TransferDirectoryTask):
						if task.has_children:
							# Folder clicked indicates a parent task has been clicked and to freeze its progress
							task.folder_clicked = True
					elif task.parents:
						for parent in task.parents:
							if not parent.folder_clicked:
								parent.size -= 1
				task.state = state_to

	def _sync_view(self):
		# This value was set to True to prevent the treeview from freezing.
		if not self.queue.mutex.acquire(blocking=True):
			return
		if not self._tv_lock.acquire(blocking=False):
			self.queue.mutex.release()
			return
		for task in self.queue.queue:
			parent_treerowref = None
			if task.parents:
				parent_treerowref = task.parents[-1].treerowref
				if parent_treerowref is None:
					continue
				parent_path = parent_treerowref.get_path()
				if parent_path is None:
					continue
				parent_treerowref = self._tv_model.get_iter(parent_path)
			if not isinstance(task, TransferTask):
				continue
			if task.treerowref is None:
				direction = Gtk.STOCK_GO_FORWARD if task.transfer_direction == 'upload' else Gtk.STOCK_GO_BACK
				image = self.treeview_transfer.render_icon(direction, Gtk.IconSize.BUTTON, None) if parent_treerowref is None else Gtk.Image()
				treeiter = self._tv_model.append(parent_treerowref, [
					image,
					task.local_path,
					task.remote_path,
					task.state,
					0,
					boltons.strutils.bytes2human(task.size) if not isinstance(task, TransferDirectoryTask) else None
				])
				task.treerowref = Gtk.TreeRowReference(self._tv_model, self._tv_model.get_path(treeiter))
			else:
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
	"""
	Base directory object that is used by both the remote and local directory to
	get and render directory data.
	"""
	def __init__(self, builder, application, default_directory):
		self.application = application
		self.treeview = builder.get_object('SFTPClientGUI.' + self.treeview_name)
		self.default_directory = default_directory
		self.cwd = self.default_directory
		self.col_name = Gtk.CellRendererText()
		self.col_name.connect('edited', self.signal_text_edited)
		col_text = Gtk.CellRendererText()
		col_img = Gtk.CellRendererPixbuf()

		col = Gtk.TreeViewColumn('Files')
		col.pack_start(col_img, False)
		col.pack_start(self.col_name, True)
		col.add_attribute(self.col_name, 'text', 0)
		col.add_attribute(col_img, 'pixbuf', 1)
		col.set_property('resizable', True)
		col.set_sort_column_id(0)

		self.treeview.append_column(col)
		self.treeview.append_column(get_treeview_column('Permissions', col_text, 3, m_col_sort=3, resizable=True))
		self.treeview.append_column(get_treeview_column('Size', col_text, 4, m_col_sort=5, resizable=True))
		self.treeview.append_column(get_treeview_column('Date Modified', col_text, 6, m_col_sort=6, resizable=True))

		self.treeview.connect('button_press_event', self.signal_tv_button_press)
		self.treeview.connect('key-press-event', self.signal_tv_key_press)
		self.treeview.connect('row-expanded', self.signal_tv_expand_row)
		self.treeview.connect('row-collapsed', self.signal_tv_collapse_row)
		self._tv_model = Gtk.TreeStore(str, GdkPixbuf.Pixbuf, str, str, str, GTYPE_LONG, str)
		self.treeview.set_model(self._tv_model)

		self.local_hidden = True
		self._get_popup_menu()
		self.load_dirs(self.cwd)

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

	def _get_raw_time(self, fullname):
		return self.stat(fullname).st_mtime

	def _rename_selection(self):
		selection = self.treeview.get_selection()
		_, treeiter = selection.get_selected()
		self.rename(treeiter)

	def _check_perm(self, fullname):
		mode = self.stat(fullname).st_mode
		perm = ''
		perm += 'r' if bool(mode & stat.S_IRUSR) else '-'
		perm += 'w' if bool(mode & stat.S_IWUSR) else '-'
		perm += 'x' if bool(mode & stat.S_IXUSR) else '-'

		perm += 'r' if bool(mode & stat.S_IRGRP) else '-'
		perm += 'w' if bool(mode & stat.S_IWGRP) else '-'
		perm += 'x' if bool(mode & stat.S_IXGRP) else '-'

		perm += 'r' if bool(mode & stat.S_IROTH) else '-'
		perm += 'w' if bool(mode & stat.S_IWOTH) else '-'
		perm += 'x' if bool(mode & stat.S_IXOTH) else '-'
		return perm

	def change_cwd(self, new_dir):
		"""
		Changes current working directory to given parameter.

		:param str new_dir: The directory to change the CWD to.
		"""
		self.cwd = new_dir
		self._chdir(self.cwd)
		self._tv_model.clear()
		self.load_dirs(new_dir)

	def get_is_folder(self, fullname):
		"""
		Checks if the given path is for a folder.

		:param str fullname: The path to be checked.
		:return bool: True if the path is a folder, false if otherwise.
		"""
		return stat.S_ISDIR(self.stat(fullname).st_mode)

	def get_file_size(self, fullname, stat_override=None):
		"""
		Gets the file size of a given file.

		:param str fullname: The path of the file to be checked.
		:param stat_override: A keyword arguement used to override the native stat function used by the class.
		:return int: A file size in bytes.
		"""
		if stat_override is not None:
			return stat_override(fullname).st_size
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
		"""
		Rename a specific row in the TreeView.

		:param treeiter: A TreeIter pointing to the selected row.
		"""
		path = self._tv_model.get_path(treeiter)
		parent = self._tv_model.iter_parent(treeiter)
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
		try:
			self.load_dirs(new_path, treeiter)
		except (OSError, IOError):
			pass
		self._tv_model.remove(self._tv_model.iter_children(treeiter))

	def load_dirs(self, path, parent=None):
		"""
		A method for loading the contents of a given path.

		:param path: The absolute path to be loaded from.
		:param parent: The TreeIter parent of the path, to be used in
		creating the TreeModel.
		"""
		for name in self._yield_dir_list(path):
			self.create_model_entry(path, parent, name)

	def create_model_entry(self, path, parent, name):
		"""
		Creates a row in the directory model containing a file or directory with
		its respective name, icon, size, date, and permissions.

		:param str path: The filepath of the folder the file is in.
		:param parent: A TreeIter object pointing to the parent node.
		:param str name: The name of the file.
		"""
		if self.local_hidden and name.startswith('.'):
			return
		if not path.endswith('/'):
			path = path + '/'
		fullname = path + name
		try:
			perm = self._check_perm(fullname)
			raw_time = self._get_raw_time(fullname)
			date = datetime.datetime.fromtimestamp(raw_time)
			date_modified = '   ' + utilities.format_datetime(date)
			is_folder = self.get_is_folder(fullname)
		except (OSError, IOError):
			icon = Gtk.IconTheme.get_default().load_icon('emblem-unreadable', 13, 0)
			self._tv_model.append(parent, [name, icon, fullname, None, None, None, None])
			return
		if is_folder:
			icon = Gtk.IconTheme.get_default().load_icon('folder', 20, 0)
			current = self._tv_model.append(parent, (name, icon, fullname, perm, None, -1, date_modified))
		else:
			file_size = self.get_file_size(fullname)
			hr_file_size = '   ' + boltons.strutils.bytes2human(file_size)
			icon = Gtk.IconTheme.get_default().load_icon('text-x-preview', 12.5, 0)
			current = self._tv_model.append(parent, (name, icon, fullname, perm, hr_file_size, file_size, date_modified))
		if is_folder:
			self._tv_model.append(current, [None, None, None, None, None, None, None])

	def signal_menu_toggled_hidden_files(self, _):  # pylint: disable=method-hidden
		self.local_hidden = not self.local_hidden
		self.refresh()

	def signal_menu_activate_collapse_all(self, _):
		self.treeview.collapse_all()

	def refresh(self, node='/'):
		"""
		Updates the model to reflect additions and removals from other commands.

		:param str node: Keyword arguement that shows the path to be refreshed.
		"""
		node = os.path.abspath(node)
		model = self._tv_model
		exp_lines = []
		model.foreach(lambda _, path, __: exp_lines.append(Gtk.TreeRowReference(model, path)) if self.treeview.row_expanded(path) and model[path][2].startswith(node) else 0)
		_iter = model.get_iter_first()
		path = model.get_path(_iter)
		counter = 1
		if model[path][2].startswith(node):
			exp_lines.insert(0, Gtk.TreeRowReference(model, path))
			counter = 0
		for path in exp_lines:
			path = path.get_path()
			old_dir_list = []
			parent = model.get_iter(path)
			if counter == 0:
				child = parent
				parent = None
				parsed_name = '/'.join(model[path][2].split('/')[:-1])
				parsed_name = parsed_name if parsed_name != '' else self.cwd
				parent_path = parsed_name
				dir_list = [os.path.join(parent_path, name) for name in self._yield_dir_list(parent_path, hide=self.local_hidden)]
			else:
				child = model.iter_children(parent)
				parent_path = model[parent][2]
				dir_list = [os.path.join(parent_path, name) for name in self._yield_dir_list(model[path][2], hide=self.local_hidden)]
			while child is not None:
				old_dir_list.append((model[child][2], Gtk.TreeRowReference(model, model.get_path(child))))
				child = model.iter_next(child)
			# this is where we add new entries to the model
			for dir in dir_list:
				if not dir.startswith(node):
					continue
				if dir not in [name_and_ref[0] for name_and_ref in old_dir_list]:
					self.create_model_entry(parent_path, parent, dir.split('/')[-1])
			# this is where we remove missing entries from the model
			for name_and_ref in old_dir_list:
				dir = name_and_ref[0]
				if not dir.startswith(node):
					continue
				if dir not in dir_list:
					model.remove(model.get_iter(name_and_ref[1].get_path()))
			counter += 1

	def signal_menu_activate_create_folder(self, _):
		selection = self.treeview.get_selection()
		_, treeiter = selection.get_selected()
		if treeiter is not None:
			path = self._tv_model.get_path(treeiter)
		if treeiter is None:
			current = self._tv_model.append(treeiter, [' ', None, None, None, None, None, None])
			self.rename(current)
			return
		if not self.treeview.row_expanded(path):
			self.treeview.expand_row(path, False)
		if self._tv_model.iter_children(treeiter) is None:
			# If no children, one dummy node must be created to make row expandable and the other to be used as a placemark for new folder
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
			new_path = self.cwd + '/' + text
		else:
			new_path = self._tv_model[parent][2] + '/' + text
		text = text.strip()
		if not text or text == self._tv_model[_iter][0]:
			self.refresh()
			return
		if self._already_exists(new_path):
			gui_utilities.show_dialog_error('Unable to make directory', self.application.get_active_window(), "Directory: {0} already exists".format(new_path))
			self.refresh()
			return
		if self._tv_model[_iter][2] is not None:
			try:
				self._rename_file(_iter, new_path)
			except (OSError, IOError):
				gui_utilities.show_dialog_error('Error', self.application.get_active_window(), 'Error renaming file')
		else:
			self._tv_model.remove(_iter)
			try:
				self._make_file(new_path)
			except (OSError, IOError):
				gui_utilities.show_dialog_error('Error', self.application.get_active_window(), 'Error creating file')
		self.refresh()

	def signal_menu_activate_delete_prompt(self, _):
		self._delete_selection()

class LocalDirectory(DirectoryBase):
	"""
	Local Directory object that defines private methods for rendering local data
	using the os module.
	"""
	transfer_direction = 'upload'
	treeview_name = 'treeview_local'
	def __init__(self, builder, application):
		self.stat = os.stat
		self._chdir = os.chdir
		super(LocalDirectory, self).__init__(builder, application, os.path.abspath(os.sep))

	def _yield_dir_list(self, path, hide=False):
		for name in os.listdir(path):
			if hide and name.startswith('.'):
				pass
			else:
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

	@handle_permission_denied
	def delete(self, model, treeiter):
		"""
		Deletes the selected file.

		:param model: The TreeModel to be used.
		:param treeiter: The TreeIter that points to
		the selected file.
		"""
		if model[treeiter][5] == -1:
			shutil.rmtree(model[treeiter][2])
		else:
			os.remove(model[treeiter][2])
		gui_utilities.show_dialog_warning('Successfully deleted ' + model[treeiter][2], self.application.get_active_window())
		self.refresh()

	@handle_permission_denied
	def remove_by_folder_name(self, name):
		"""
		Removes a folder given its absolute path.

		:param name: The path of the folder to be removed.
		"""
		shutil.rmtree(name)

	@handle_permission_denied
	def remove_by_file_name(self, name):
		"""
		Removes a file given its absolute path.

		:param name: The path of the file to be removed.
		"""
		os.remove(name)

	def get_abs_path(self, path):
		"""
		Get the absolute path of a given path.

		:param path: The path to get the absolute path from.
		:return str: The absolute path of the path.
		"""
		return os.path.abspath(path)

	def walk(self, src_file, src, commands, local_name, old_files):
		"""
		Walk through a given directory and return all subdirectories and
		subfiles in a format parsed for transfer.

		:param str src_file: The Directory to be traversed through.
		:param commands: The list to be updated with the file list.
		:param str local_name: The name selected by the user, used
		to modify the path to be relative to selected directory.
		:param old_file: Dictionary used to keep track of the original
		file names.
		"""
		for walker in os.walk(src_file):
			walker = list(walker)
			temp = walker[0].split('/')
			loc = temp.index(local_name)
			# Parse the name relative to the directory selected, i.e /home/osboxes/Music -> /osboxes/Music if osboxes was selected
			parsed_name = '/'.join(temp[loc:])
			old_files[parsed_name] = walker[0]
			walker[0] = parsed_name
			commands.append(walker)

class RemoteDirectory(DirectoryBase):
	"""
	Remote Directory object that defines private methods for rendering remote
	data using Paramiko's SFTP functionality.
	"""
	transfer_direction = 'download'
	treeview_name = 'treeview_remote'
	def __init__(self, builder, application, ftp, ssh):
		self.ftp = ftp
		self.ssh = ssh
		self.stat = ftp.stat
		self._chdir = self.ftp.chdir
		super(RemoteDirectory, self).__init__(builder, application, application.config['server_config']['server.web_root'])

	def _yield_dir_list(self, path, hide=False):
		for name in self.ftp.listdir(path):
			if hide and name.startswith('.'):
				pass
			else:
				yield name

	def _already_exists(self, path):
		try:
			self.ftp.stat(path)
		except IOError as error:
			if error.errno == errno.ENOENT:
				return False
			else:
				raise error
		return True

	def _rename_file(self, _iter, path):
		self.ftp.rename(self._tv_model[_iter][2], path)  # pylint: disable=unsubscriptable-object

	@handle_permission_denied
	def _make_file(self, path, ftp=None):
		# If method called when self.ftp is busy, alternate ftp is specified, prevents Garbage Packet Error
		if ftp is None:
			ftp = self.ftp
		ftp.mkdir(path)

	@handle_permission_denied
	def delete(self, model, treeiter):
		"""
		Deletes the selected file.

		:param model: The TreeModel to be used.
		:param treeiter: The TreeIter that points to
		the selected file.
		"""
		name = self._tv_model[treeiter][2]  # pylint: disable=unsubscriptable-object
		if self.get_is_folder(name):
			if not self.remove_by_folder_name(name):
				return
		elif not self.remove_by_file_name(name):
			return
		gui_utilities.show_dialog_warning('Successfully deleted ' + name, self.application.get_active_window())
		self.refresh()

	@handle_permission_denied
	def remove_by_folder_name(self, name):
		"""
		Removes a folder given its absolute path.

		:param name: The path of the folder to be removed.
		"""
		# with paramiko, you cannot remove populated dir, so recursive method utilized
		for path in self._yield_dir_list(name):
			new_path = os.path.join(name, path)
			if self.get_is_folder(new_path):
				self.remove_by_folder_name(new_path)
			else:
				self.remove_by_file_name(new_path)
		self.ftp.rmdir(name)

	@handle_permission_denied
	def remove_by_file_name(self, name):
		"""
		Removes a file given its absolute path.

		:param name: The path of the file to be removed.
		"""
		self.ftp.remove(name)

	def get_abs_path(self, path):
		"""
		Get the absolute path of a given path.

		:param path: The path to get the absolute path from.
		:return str: The absolute path of the path.
		"""
		return os.path.join(self.cwd, path)

	def walk(self, directory, src, commands, remote_name, old_files):
		"""
		Walk through a given directory and return all subdirectories and
		subfiles in a format parsed for transfer.

		:param str directory: The Directory to be traversed through.
		:param commands: The list to be updated with the file list.
		:param str remote_name: The name selected by the user, used
		to modify the path to be relative to selected directory.
		:param old_file: Dictionary used to keep track of the original
		file names.
		"""
		subdirs = []
		files = []
		temp = directory.split('/')
		loc = temp.index(remote_name)
		parsed_name = '/'.join(temp[loc:])
		for f in src._yield_dir_list(directory):
			if src.get_is_folder(directory + '/' + f):
				subdirs.append(f)
			else:
				files.append(f)
		command = [parsed_name, subdirs, files]
		commands.append(command)
		old_files[parsed_name] = directory
		for folder in subdirs:
			new_path = os.path.join(directory, folder)
			self.walk(new_path, src, commands, remote_name, old_files)

	def _already_exists_all(self, path):
		# using self.ftp causes collision errors and raises Garbage Packet Error
		backup_ftp = self.ssh.open_sftp()
		try:
			backup_ftp.stat(path)
		except IOError as error:
			backup_ftp.close()
			if error.errno == errno.ENOENT or error.errno == errno.EACCES:
				return False
			raise
		else:
			backup_ftp.close()
			return True

class FileManager(object):
	"""
	File manager that manages the Transfer Queue by adding new tasks and
	handling tasks put in, as well as handles communication between all the
	other classes.
	"""
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
		self.remote = RemoteDirectory(self.builder, self.application, ftp, ssh)
		self.builder.get_object('button_upload').connect('button-press-event', lambda widget, event: self._queue_transfer(UploadTask))
		self.builder.get_object('button_download').connect('button-press-event', lambda widget, event: self._queue_transfer(DownloadTask))
		self.local.menu_item_transfer.connect('activate', lambda widget: self._queue_transfer(UploadTask))
		self.remote.menu_item_transfer.connect('activate', lambda widget: self._queue_transfer(DownloadTask))

		box_local = self.builder.get_object('box_local_dropdown')
		self._local_dropdown_model = Gtk.ListStore(str)
		self.render_dropdown(self._local_dropdown_model, self.local)
		self.local_dropdown = Gtk.ComboBox.new_with_model_and_entry(self._local_dropdown_model)
		self.local_dropdown.set_entry_text_column(0)
		self.local_dropdown.connect('changed', self.signal_combo_changed, self.local)
		box_local.pack_start(self.local_dropdown, True, True, 0)

		box_remote = self.builder.get_object('box_remote_dropdown')
		self._remote_dropdown_model = Gtk.ListStore(str)
		self.render_dropdown(self._remote_dropdown_model, self.remote)
		self.remote_dropdown = Gtk.ComboBox.new_with_model_and_entry(self._remote_dropdown_model)
		self.remote_dropdown.set_entry_text_column(0)
		self.remote_dropdown.connect('changed', self.signal_combo_changed, self.remote)
		box_remote.pack_start(self.remote_dropdown, True, True, 0)

		self.window.connect('destroy', self.signal_window_destroy)
		self.window.show_all()

	@handle_permission_denied
	def signal_combo_changed(self, combo, system):
		treeiter = combo.get_active_iter()
		model = combo.get_model()
		if treeiter is not None:
			new_dir = model[treeiter][0]
		else:
			# the user has typed something into the combo box
			new_dir = CURRENT_DIRECTORY
			entry = combo.get_child().get_text()
			entry = system.get_abs_path(entry)
			if entry != PARENT_DIRECTORY and system._already_exists_all(entry) and entry != system.cwd:
				if system.get_is_folder(entry):
					# if the entered string is valid
					new_dir = entry
		if new_dir != CURRENT_DIRECTORY:
			if new_dir == PARENT_DIRECTORY:
				split = system.cwd.split('/')
				split = split[:-1]
				new_dir = '/'.join(split)
				if new_dir == '':
					new_dir = '/'
			system.change_cwd(new_dir)
			model.clear()
			self.render_dropdown(model, system)

	def render_dropdown(self, model, system):
		"""
		Populates the dropdown menu with the CWD children.

		:param model: The TreeModel being used.
		:type model: :py:class:`Gtk.TreeModel`
		:param system: The filesystem being used, either self.local or self.remote
		"""
		model.append((PARENT_DIRECTORY,))
		for _dir in system._yield_dir_list(system.cwd):
			filename = os.path.join(system.cwd, _dir)
			if 'r' not in system._check_perm(filename):
				continue
			elif not system.get_is_folder(filename):
				continue
			elif system.local_hidden and _dir.startswith('.'):
				continue
			model.append((filename,))

	def render_menubar(self, menubar):
		"""
		Populates the menu-bar as well as sets the menu check-box values to
		their defaults.

		:param menubar: The menu-bar to populate.
		"""
		self.validate = False
		menu_item = Gtk.CheckMenuItem.new_with_label('Checksum Validation')
		menu_item.connect('toggled', self.signal_toggled_validate_checksums)
		self.validate_checksums = menu_item
		menubar.append(menu_item)

		self.transfer_hidden = True
		menu_item = Gtk.CheckMenuItem.new_with_label('Transfer Hidden Files')
		menu_item.connect('toggled', self.signal_toggled_transfer_hidden)
		self.signal_toggled_transfer_hidden = menu_item
		menubar.append(menu_item)

		menu_item = Gtk.SeparatorMenuItem()
		menubar.append(menu_item)

		menu_item = Gtk.MenuItem.new_with_label('Exit')
		menu_item.connect('activate', self.signal_shutdown_activate)
		menubar.append(menu_item)

	def signal_shutdown_activate(self, _):
		self.signal_window_destroy(None)
		self.window.destroy()

	def signal_toggled_transfer_hidden(self, _):  # pylint: disable=method-hidden
		self.transfer_hidden = not self.transfer_hidden

	def signal_toggled_validate_checksums(self, _):
		self.validate = not self.validate

	def _transfer_folder(self, task, ssh):
		task.state = 'Transferring'
		if task.parents:
			# prevents any lagging folders/files from causing issues
			if task.parents[0].state in ('Cancelled', 'Paused'):
				task.state = task.parents[0].state
				return
		if isinstance(task, UploadDirectoryTask):
			new_dir = task.remote_path
			dst = self.remote
			if dst._already_exists_all(new_dir):
				return
			ftp = ssh.open_sftp()
			dst._make_file(new_dir, ftp=ftp)
			ftp.close()
		elif isinstance(task, DownloadDirectoryTask):
			new_dir = task.local_path
			dst = self.local
			if dst._already_exists_all(new_dir):
				return
			dst._make_file(new_dir)
		if task.empty:
			task.size = 0
			task.transferred = 0
			task.state = 'Completed'

	def _transfer(self, task, ssh, chunk=0x1000):
		task.state = 'Transferring'
		ftp = ssh.open_sftp()
		write_mode = 'ab+' if task.transferred > 0 else 'wb+'
		try:
			if isinstance(task, UploadTask):
				src_file_h = open(task.local_path, 'rb')
				dst_file_h = ftp.file(task.remote_path, write_mode)
			elif isinstance(task, DownloadTask):
				src_file_h = ftp.file(task.remote_path, 'rb')
				dst_file_h = open(task.local_path, write_mode)
			else:
				raise ValueError('unsupported task type passed to _transfer')
			src_file_h.seek(task.transferred)
			while task.transferred < task.size:
				if self._threads_shutdown.is_set():
					task.state = 'Cancelled'
				if task.state != 'Transferring':
					break
				temp = src_file_h.read(chunk)
				dst_file_h.write(temp)
				task.transferred += chunk
			if task.state == 'Cancelled':
				if isinstance(task, UploadTask):
					self.remote.remove_by_file_name(task.remote_path)
				elif isinstance(task, DownloadTask):
					self.local.remove_by_file_name(task.local_path)
			elif task.state == 'Paused':
				pass
			else:
				task.state = 'Completed'
				#if self.validate:
					# todo: if server-side hashing is not supported then skip the validation
					#src_file_h.seek(0)
					#dst_file_h.seek(0)
					#src_hash = hashlib.md5(src_file_h.read()).hexdigest()
					#dst_hash = hashlib.md5(dst_file_h.read()).hexdigest()
					#if src_hash == dst_hash:
						#logger.info("{0} and {1} have been validated with a sum of {2}".format(task.local_path, task.remote_path, src_hash))
					#else:
						#logger.warning("{0} and {1} were not properly transferred with the sums {2} and {3}".format(task.local_path, task.remote_path, src_hash, dst_hash))
				if task.parents:
					for parent_task in task.parents:
						parent_task.transferred += 1
						if parent_task.transferred >= parent_task.size:
							parent_task.state = 'Completed'
							if not parent_task.parents:
								GLib.idle_add(self._idle_refresh_directories)
				else:
					GLib.idle_add(self._idle_refresh_directories)
			src_file_h.close()
			dst_file_h.close()
		except Exception:
			logger.error("Unknown error transferring {0} and {1}".format(task.local_path, task.remote_path), exc_info=True)
			if not task.is_done:
				task.state = 'Error'
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
		self.window.set_sensitive(False)
		self._threads_shutdown.set()
		for _ in self._threads:
			self.queue.put(ShutdownTask())
		for thread in self._threads:
			thread.join()
		self.ftp.close()

	def _queue_transfer(self, task_cls):
		selection = self.local.treeview.get_selection()
		model, treeiter = selection.get_selected()
		if treeiter is None:
			local_file = self.local.cwd
			local_name = local_file.split('/')
			local_name = local_name[-1]
		else:
			local_file = model[treeiter][2]
			local_name = model[treeiter][0]

		selection = self.remote.treeview.get_selection()
		model, treeiter = selection.get_selected()
		if treeiter is None:
			remote_file = self.remote.cwd
			remote_name = remote_file.split('/')
			remote_name = remote_name[-1]
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
			self.handle_file_transfer(task_cls, local_file, src_file, dst_file, dst_dir, dst)

	def handle_file_transfer(self, task_cls, local_file, src_file, dst_file, dst_dir, dst):
		"""
		Handles the file transfer by stopping bad transfers, creating tasks for
		transfers, and placing them in the queue.

		:param task_cls: The type of task the transfer will be.
		:param str local_file: The local file involved in the transfer.
		:param str src_file: The file to be uploaded or downloaded.
		:param str dst_file: The file to be created.
		:param str dst_dir: The folder the file will be placed in.
		:param dst: The filesystem of the destination.
		"""
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
			if not dst._already_exists(dst_file):
				if not dst._make_file(dst_file):
					return
				dst.remove_by_folder_name(dst_file)
			local_file, remote_file = src_file, dst_file
		file_task = task_cls(local_file, remote_file)
		if isinstance(file_task, UploadTask):
			file_size = self.local.get_file_size(local_file)
		elif isinstance(file_task, DownloadTask):
			file_size = self.remote.get_file_size(remote_file)
		file_task.size = file_size
		self.queue.put(file_task)

	def handle_folder_transfer(self, task_cls, remote_name, local_name, src, dst, src_file, dst_file, dst_dir, remote_file, local_file):
		"""
		Handles the folder transfer by stopping bad transfers, creating tasks
		for transfers, and placing them in the queue.

		:param task_cls: The type of task the transfer will be.
		:param str remote_name: The name of the remote folder.
		:param str local_name: The name of the local folder.
		:param str local_file: The local folder involved in the transfer.
		:param str remote_file: The remote folder involved in the transfer.
		:param str src_file: The folder to be uploaded or downloaded.
		:param str dst_file: The folder to be created.
		:param str dst_dir: The folder the folder will be placed in.
		:param src: The filesystem of the source.
		:param dst: The filesystem of the destination.
		"""
		commands = []
		old_files = {}
		uload = False
		if issubclass(task_cls, UploadTask):
			name = local_name
			uload = True
			if not os.access(src_file, os.R_OK):
				return
			if not dst._already_exists(dst_file):
				if not dst._make_file(dst_file):
					return
				dst.remove_by_folder_name(dst_file)
		elif issubclass(task_cls, DownloadTask):
			name = remote_name
			if not os.access(dst_dir, os.W_OK):
				return
		src.walk(src_file, src, commands, name, old_files)
		parents = []
		all_parents = []
		for command in commands:
			hidden = False
			new_dir = dst_dir + '/' + command[0]
			old_dir = old_files[command[0]]
			if self.transfer_hidden:
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
			temp = command[0].split('/')
			for i in range(0, len(temp)):
				# look for every new directory or subdirectory in path and make it a task
				name = '/'.join(temp[0:i + 1])
				parent_task = (parents[i - 1][0],) if i > 0 else 0
				if not uload:
					task = (DownloadDirectoryTask(new_dir, old_dir, parents=parent_task), name)
				else:
					task = (UploadDirectoryTask(old_dir, new_dir, parents=parent_task), name)
				if i >= len(parents):
					parents.append(task)
					all_parents.append(task)
					self.queue.put(task[0])
				elif name != parents[i][1]:
					parents[i] = task
					all_parents.append(task)
					self.queue.put(task[0])

			for i in range(0, len(parents) - len(temp)):
				parents.pop()
			for _file in command[2]:
				if _file.startswith('.') and self.transfer_hidden:
					continue
				new_file = new_dir + '/' + _file
				old_file = old_files[command[0]] + '/' + _file
				if uload and not os.access(old_file, os.R_OK):
					logger.warning("cannot read file {0}".format(old_file))
					continue
				if not src._already_exists_all(old_file):
					logger.warning("{0} is neither a file nor folder".format(old_file))
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
					actual_parents.append(parent[0])  # List of parent TASKS
				file_task = task_cls(local_file, remote_file, parents=actual_parents)
				if isinstance(file_task, UploadTask):
					file_size = self.local.get_file_size(local_file)
				elif isinstance(file_task, DownloadTask):
					file_size = self.remote.get_file_size(remote_file)
				file_task.size = file_size
				self.queue.put(file_task)
		for parent in all_parents:
			if parent[0].size is None:
				parent[0].empty = True
