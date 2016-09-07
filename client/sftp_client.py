# todo: make show hidden files an option for both and persist the setting
import collections
import contextlib
import datetime
import errno
import logging
import os
import posixpath
import stat
import shutil
import threading
import time

from king_phisher import its
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

if its.on_windows:
	import win32api
	import win32con

GTYPE_LONG = GObject.type_from_name('glong')
PARENT_DIRECTORY = '..'
CURRENT_DIRECTORY = '.'

gtk_builder_file = os.path.splitext(__file__)[0] + '.ui'
logger = logging.getLogger('KingPhisher.Plugins.SFTPClient')
DirectoryContents = collections.namedtuple('DirectoryContents', ('dirpath', 'dirnames', 'filenames'))
ObjectLock = collections.namedtuple('ObjectLock', ('object', 'lock'))

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
	req_min_version = '1.4.0b0'
	version = '1.0'
	def initialize(self):
		"""Connects to the start SFTP Client Signal to the plugin and checks for .ui file."""
		self.sftp_window = None
		if not os.access(gtk_builder_file, os.R_OK):
			gui_utilities.show_dialog_error(
				'Plugin Error',
				self.application.get_active_window(),
				"The GTK Builder data file ({0}) is not available.".format(os.path.basename(gtk_builder_file))
			)
			return False
		if 'directories' not in self.config:
			self.config['directories'] = {}
		if 'transfer_hidden' not in self.config:
			self.config['transfer_hidden'] = False
		if 'show_hidden' not in self.config:
			self.config['show_hidden'] = False
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
				manager = FileManager(self.application, ssh, self.config)
			except paramiko.ssh_exception.ChannelException as error:
				self.logger.error('an ssh channel exception was raised while initializing', exc_info=True)
				if len(error.args) == 2:
					details = "SSH Channel Exception #{0} ({1})".format(*error.args)
				else:
					details = 'An unknown SSH Channel Exception occurred.'
				gui_utilities.show_dialog_error('SSH Channel Exception', self.application.get_active_window(), details)
				return
			except paramiko.ssh_exception.SSHException:
				self.logger.error('an ssh exception was raised while initializing', exc_info=True)
				gui_utilities.show_dialog_error('SSH Exception', self.application.get_active_window(), 'An error occurred in the SSH transport.')
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
		logger.debug('queued task: ' + str(task))

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
	def __str__(self):
		return 'shutdown'

class TransferTask(Task):
	"""
	Task used to model transfers. Each task is put in the queue where it will be
	pass into the _transfer method of the FileManager class for the transfer to
	occur.
	"""
	_states = ('Active', 'Cancelled', 'Completed', 'Error', 'Paused', 'Pending', 'Transferring')
	__slots__ = ('_state', 'local_path', 'remote_path', 'size', 'transferred', 'treerowref', 'parent')
	def __init__(self, local_path, remote_path, parent=None, size=None, state=None):
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
		self.size = size
		"""
		If the task is a file transfer, an integer of the total number of bytes,
		if the task is a directory transfer, the total number of children files.
		"""
		self.treerowref = None
		"""A TreeRowReference object representing the Tasks position in the treeview."""
		self.parent = parent

	def __repr__(self):
		return "<{0} local_path={1!r} remote_path={2!r} state={3!r}>".format(self.__class__.__name__, self.local_path, self.remote_path, self.state)

	@property
	def parents(self):
		parents = []
		node = self
		while node.parent is not None:
			parents.append(node.parent)
			node = node.parent
		return parents

	@property
	def progress(self):
		if self.size is None:
			percent = 0
		elif self.size == 0:
			percent = 1
		else:
			percent = (float(self.transferred) / float(self.size))
		return min(int(percent * 100), 100)

	@property
	def state(self):
		return Task.state.fget(self)

	@state.setter
	def state(self, value):
		if value == Task.state.fget(self):
			return
		Task.state.fset(self, value)
		if value in ('Cancelled', 'Completed'):
			for parent_task in self.parents:
				if value == 'Cancelled':
					parent_task.size -= 1
				else:
					parent_task.transferred += 1
				if parent_task.size == parent_task.transferred:
					parent_task.state = ('Completed' if parent_task.size else 'Cancelled')

class DownloadTask(TransferTask):
	"""
	Subclass of TransferTask that indicates
	the task is downloading files.
	"""
	transfer_direction = 'download'
	def __str__(self):
		return "download file {0} -> {1}".format(self.remote_path, self.local_path)

class UploadTask(TransferTask):
	"""
	Subclass of TransferTask that indicates
	the task is uploading files.
	"""
	transfer_direction = 'upload'
	def __str__(self):
		return "upload file {0} -> {1}".format(self.local_path, self.remote_path)

class TransferDirectoryTask(TransferTask):
	"""
	Task to model a folder transfer. Acts as a parent task
	to other TransferTasks and is passed into _transfer_dir.
	"""
	pass

class DownloadDirectoryTask(DownloadTask, TransferDirectoryTask):
	"""
	Subclass of DownloadTask and TransferDirectoryTask that indicates the task
	is downloading folders.
	"""
	def __str__(self):
		return "download directory {0} -> {1}".format(self.remote_path, self.local_path)
DownloadTask.dir_cls = DownloadDirectoryTask

class UploadDirectoryTask(UploadTask, TransferDirectoryTask):
	"""
	Subclass of UploadTask and TransferDirectoryTask that indicates the task is
	uploading folders.
	"""
	def __str__(self):
		return "upload directory {0} -> {1}".format(self.remote_path, self.local_path)
UploadTask.dir_cls = UploadDirectoryTask

class DelayedChangedSignal(object):
	def __init__(self, handler, delay=500):
		self._handler = handler
		self.delay = delay
		self._lock = threading.RLock()
		self._event_id = None

	def __call__(self, *args):
		return self.changed(*args)

	def _changed(self, args):
		with self._lock:
			self._handler(*args)
			self._event_id = None
		return False

	def changed(self, *args):
		with self._lock:
			if self._event_id is not None:
				GLib.source_remove(self._event_id)
			self._event_id = GLib.timeout_add(self.delay, self._changed, args)

class StatusDisplay(object):
	"""
	Class representing the bottom treeview of the GUI. This contains the logging
	and graphical representation of all queued transfers.
	"""
	def __init__(self, builder, queue):
		self.builder = builder
		self.queue = queue
		self.scroll = self.builder.get_object('scrolledwindow_transfer_statuses')
		self.treeview_transfer = self.builder.get_object('treeview_transfer_statuses')
		self._tv_lock = threading.RLock()

		col_text = Gtk.CellRendererText()
		col_img = Gtk.CellRendererPixbuf()
		col = Gtk.TreeViewColumn('')
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
		col_bar.set_min_width(125)
		self.treeview_transfer.append_column(col_bar)

		self.treeview_transfer.append_column(get_treeview_column('Size', col_text, 5, m_col_sort=3, resizable=True))
		self._tv_model = Gtk.TreeStore(GdkPixbuf.Pixbuf, str, str, str, int, str, object)
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
		selected_tasks = set()
		for treepath in treepaths:
			treeiter = self._tv_model.get_iter(treepath)
			selected_tasks.add(self._tv_model[treeiter][6])
			self._tv_model.foreach(lambda _, path, treeiter: selected_tasks.add(self._tv_model[treeiter][6]) if path.is_descendant(treepath) else 0)
		return selected_tasks

	def _get_selected_treepaths(self):
		selection = self.treeview_transfer.get_selection()
		model, treeiter = selection.get_selected()
		if treeiter is None:
			return None
		treepaths = []
		treepaths.append(model.get_path(treeiter))
		return treepaths

	def _change_task_state(self, state_from, state_to):
		modified_tasks = []
		with self.queue.mutex:
			selected_tasks = set([task for task in self._get_selected_tasks() if task.state in state_from])
			for task in selected_tasks:
				modified_tasks.append(task)
				modified_tasks.extend(task.parents)  # ensure parents are also synced because state changes may affect them
				task.state = state_to
		self.sync_view(set(modified_tasks))

	def _sync_view(self, tasks=None):
		# This value was set to True to prevent the treeview from freezing.
		if not self.queue.mutex.acquire(blocking=True):
			return
		if not self._tv_lock.acquire(blocking=False):
			self.queue.mutex.release()
			return
		tasks = (tasks or self.queue.queue)
		for task in tasks:
			if not isinstance(task, TransferTask):
				continue
			if task.treerowref is None:
				parent_treeiter = None
				if task.parent:
					parent_treerowref = task.parent.treerowref
					if parent_treerowref is None:
						continue
					parent_treepath = parent_treerowref.get_path()
					if parent_treepath is None:
						continue
					parent_treeiter = self._tv_model.get_iter(parent_treepath)
				direction = Gtk.STOCK_GO_FORWARD if task.transfer_direction == 'upload' else Gtk.STOCK_GO_BACK
				image = self.treeview_transfer.render_icon(direction, Gtk.IconSize.BUTTON, None) if parent_treeiter is None else Gtk.Image()
				treeiter = self._tv_model.append(parent_treeiter, [
					image,
					task.local_path,
					task.remote_path,
					task.state,
					0,
					None if (task.size is None or isinstance(task, TransferDirectoryTask)) else boltons.strutils.bytes2human(task.size),
					task
				])
				task.treerowref = Gtk.TreeRowReference.new(self._tv_model, self._tv_model.get_path(treeiter))
			elif task.treerowref.valid():
				row = self._tv_model[task.treerowref.get_path()]  # pylint: disable=unsubscriptable-object
				row[3] = task.state
				row[4] = task.progress
		self.queue.mutex.release()
		return False

	def sync_view(self, tasks=None):
		if isinstance(tasks, Task):
			tasks = (tasks,)
		GLib.idle_add(self._sync_view, tasks, priority=GLib.PRIORITY_DEFAULT_IDLE)

	def signal_menu_activate_clear(self, _):
		with self.queue.mutex:
			for task in list(self.queue.queue):
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

	def signal_tv_size_allocate(self, _, event, data=None):
		adj = self.scroll.get_vadjustment()
		adj.set_value(0)

class DirectoryBase(object):
	"""
	Base directory object that is used by both the remote and local directory to
	get and render directory data.
	"""
	def __init__(self, builder, application, config, wd_history):
		self.application = application
		self.config = config
		self.treeview = builder.get_object('SFTPClientGUI.' + self.treeview_name)
		self.wd_history = collections.deque(wd_history, maxlen=3)
		self.cwd = None
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
		self._tv_model = Gtk.TreeStore(
			str,               # 0 base name
			GdkPixbuf.Pixbuf,  # 1 icon
			str,               # 2 full path
			str,               # 3 permissions
			str,               # 4 human readable size
			GTYPE_LONG,        # 5 size in bytes
			str                # 6 modified timestamp
		)
		self._tv_model.set_sort_column_id(0, Gtk.SortType.ASCENDING)
		self._tv_model_filter = self._tv_model.filter_new()
		self._tv_model_filter.set_visible_func(self._filter_entries)
		self.refilter = self._tv_model_filter.refilter
		self._tv_model_sort = Gtk.TreeModelSort(model=self._tv_model_filter)
		self.treeview.set_model(self._tv_model_sort)

		self._wdcb_model = Gtk.ListStore(str)  # working directory combobox
		self.wdcb_dropdown = builder.get_object(self.working_directory_combobox_name)
		self.wdcb_dropdown.set_model(self._wdcb_model)
		self.wdcb_dropdown.set_entry_text_column(0)
		self.wdcb_dropdown.connect('changed', DelayedChangedSignal(self.signal_combo_changed))

		self.show_hidden = False
		self._get_popup_menu()

	def _format_perm(self, st_mode):
		perm = ''
		perm += 'r' if bool(st_mode & stat.S_IRUSR) else '-'
		perm += 'w' if bool(st_mode & stat.S_IWUSR) else '-'
		perm += 'x' if bool(st_mode & stat.S_IXUSR) else '-'

		perm += 'r' if bool(st_mode & stat.S_IRGRP) else '-'
		perm += 'w' if bool(st_mode & stat.S_IWGRP) else '-'
		perm += 'x' if bool(st_mode & stat.S_IXGRP) else '-'

		perm += 'r' if bool(st_mode & stat.S_IROTH) else '-'
		perm += 'w' if bool(st_mode & stat.S_IWOTH) else '-'
		perm += 'x' if bool(st_mode & stat.S_IXOTH) else '-'
		return perm

	def _delete_selection(self):
		selection = self.treeview.get_selection()
		_, treeiter = selection.get_selected()
		if treeiter is None:
			return
		treeiter = self._treeiter_sort_to_model(treeiter)
		confirmed = gui_utilities.show_dialog_yes_no(
			'Confirm Delete',
			self.application.get_active_window(),
			"Are you sure you want to delete the selected {0}: {1}?".format(('directory' if self._tv_model[treeiter][5] == -1 else 'file'), self.path_mod.basename(self._tv_model[treeiter][2]))
		)
		if confirmed:
			self.delete(treeiter)
			selection.unselect_all()

	def _filter_entries(self, model, treeiter, _):
		if model[treeiter][0] in (None, '.', '..'):
			return True
		path = model[treeiter][2]
		if path is None:
			return True
		if not self.config['show_hidden'] and self.path_is_hidden(path):
			return False
		return True

	def _get_popup_menu(self):
		self._menu_items_req_selection = []
		self.popup_menu = Gtk.Menu.new()

		self.menu_item_transfer = Gtk.MenuItem.new_with_label(self.transfer_direction.title())
		self.popup_menu.append(self.menu_item_transfer)

		menu_item = Gtk.MenuItem.new_with_label('Collapse All')
		menu_item.connect('activate', self.signal_menu_activate_collapse_all)
		self.popup_menu.append(menu_item)

		menu_item = Gtk.MenuItem.new_with_label('Set Working Directory')
		menu_item.connect('activate', self.signal_menu_activate_set_working_directory)
		self.popup_menu.append(menu_item)
		self._menu_items_req_selection.append(menu_item)

		menu_item = Gtk.MenuItem.new_with_label('Create Folder')
		menu_item.connect('activate', self.signal_menu_activate_create_folder)
		self.popup_menu.append(menu_item)

		menu_item = Gtk.MenuItem.new_with_label('Rename')
		menu_item.connect('activate', self.signal_menu_activate_rename)
		self.popup_menu.append(menu_item)
		self._menu_items_req_selection.append(menu_item)

		menu_item = Gtk.SeparatorMenuItem()
		self.popup_menu.append(menu_item)

		menu_item = Gtk.MenuItem.new_with_label('Delete')
		menu_item.connect('activate', self.signal_menu_activate_delete_prompt)
		self.popup_menu.append(menu_item)
		self._menu_items_req_selection.append(menu_item)

		self.popup_menu.show_all()

	def _rename_selection(self):
		selection = self.treeview.get_selection()
		_, treeiter = selection.get_selected()
		treeiter = self._treeiter_sort_to_model(treeiter)
		self.rename(treeiter)

	def _treeiter_model_to_sort(self, model_treeiter):
		is_valid, filter_treeiter = self._tv_model_filter.convert_child_iter_to_iter(model_treeiter)
		if not is_valid:
			return None
		is_valid, sort_treeiter = self._tv_model_sort.convert_child_iter_to_iter(filter_treeiter)
		if not is_valid:
			return None
		return sort_treeiter

	def _treeiter_sort_to_model(self, sort_treeiter):
		filter_treeiter = self._tv_model_sort.convert_iter_to_child_iter(sort_treeiter)
		return self._tv_model_filter.convert_iter_to_child_iter(filter_treeiter)

	def _treepath_sort_to_model(self, sort_treepath):
		if isinstance(sort_treepath, str):
			sort_treepath = Gtk.TreePath(sort_treepath)
		filter_treepath = self._tv_model_sort.convert_path_to_child_path(sort_treepath)
		return self._tv_model_filter.convert_path_to_child_path(filter_treepath)

	def change_cwd(self, new_dir):
		"""
		Changes current working directory to given parameter.

		:param str new_dir: The directory to change the CWD to.
		:return: The absolute path of the new working directory if it was changed.
		:rtype: str
		"""
		if not self.path_mod.isabs(new_dir):
			new_dir = self.get_abspath(new_dir)
		if new_dir == self.cwd:
			return
		self._chdir(new_dir)
		self.cwd = new_dir
		self._tv_model.clear()
		self.load_dirs(new_dir)
		# clear and rebuild the model
		self._wdcb_model.clear()
		self._wdcb_model.append((self.root_directory,))
		if self.default_directory != self.root_directory:
			self._wdcb_model.append((self.default_directory,))
		if new_dir not in self.wd_history and gui_utilities.gtk_list_store_search(self._wdcb_model, new_dir) is None:
			self.wd_history.appendleft(new_dir)
		for directory in self.wd_history:
			self._wdcb_model.append((directory,))
		active_iter = gui_utilities.gtk_list_store_search(self._wdcb_model, new_dir)
		self.wdcb_dropdown.set_active_iter(active_iter)
		return new_dir

	def get_abspath(self, path):
		"""
		Get the absolute path of a given path.

		:param path: The path to get the absolute path from.
		:return str: The absolute version of the path.
		"""
		return self.path_mod.abspath(self.path_mod.join(self.cwd, path))

	def get_relpath(self, path, start=None):
		"""
		Get the relative path of a given path.

		:param path: The path to get the relative path from.
		:return str: The relative version of the path.
		"""
		return self.path_mod.relpath(path, start=(start or self.cwd))

	def get_is_folder(self, fullname):
		"""
		Checks if the given path is for a folder.

		:param str fullname: The path to be checked.
		:return bool: True if the path is a folder, false if otherwise.
		"""
		try:
			result = stat.S_ISDIR(self.stat(fullname).st_mode)
		except (IOError, OSError):
			return False
		return result

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

	def path_is_hidden(self, path):
		"""
		Used to determine if the file or directory located at *path* is hidden.
		On Windows this uses the Windows API, on any other operating system this
		checks that the basename of the path begins with '.'.

		:param path: The path to iterate through to determine if it is hidden.
		:return: True if any part of the path is hidden
		:rtype: bool
		"""
		raise NotImplementedError()

	def path_mode(self, path):
		"""
		Return the portion of the st_mode member of a stat operation which
		indicates the type of the path. If the path does not exist, zero is
		returned. The return value is suitable for use with the
		:py:func:`stat.S_ISREG` and :py:func:`stat.S_ISDIR` functions.

		:param stat path: The path to entry to check.
		:return: The mode of the specified path.
		:rtype: bool
		"""
		raise NotImplementedError()

	def shutdown(self):
		"""Perform any necessary clean up operations."""
		pass

	def signal_combo_changed(self, combobox):
		new_dir = combobox.get_active_text()
		if not new_dir:
			return
		if not self.path_mod.isabs(new_dir):
			new_dir = self.get_abspath(new_dir)
		entry = combobox.get_child()
		if not self.get_is_folder(new_dir):
			entry.set_property('primary-icon-name', 'dialog-warning')
			return
		try:
			with gui_utilities.gobject_signal_blocked(combobox, 'changed'):
				self.change_cwd(new_dir)
		except (IOError, OSError):
			entry.set_property('primary-icon-name', 'dialog-warning')
		else:
			entry.set_property('primary-icon-name', 'gtk-apply')
			entry.set_text(new_dir)

	def signal_tv_button_press(self, _, event):
		if event.button == Gdk.BUTTON_SECONDARY:
			_, treeiter = self.treeview.get_selection().get_selected()
			sensitive = treeiter is not None
			for menu_item in self._menu_items_req_selection:
				menu_item.set_sensitive(sensitive)
			self.popup_menu.popup(None, None, None, None, event.button, Gtk.get_current_event_time())
			return True
		return

	def signal_tv_key_press(self, _, event):
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
		base_path = self._tv_model.get_path(treeiter)
		filter_path = self._tv_model_filter.convert_child_path_to_path(base_path)
		sort_path = self._tv_model_sort.convert_child_path_to_path(filter_path)

		col = self.treeview.get_column(0)
		self.col_name.set_property('editable', True)
		self.treeview.set_cursor(sort_path, col, True)
		self.col_name.set_property('editable', False)

	def signal_menu_activate_rename(self, _):
		self._rename_selection()

	def signal_menu_activate_set_working_directory(self, _):
		model, treeiter = self.treeview.get_selection().get_selected()
		if not treeiter:
			return
		self.change_cwd(model[treeiter][2])

	def signal_tv_collapse_row(self, _, treeiter, treepath):
		treeiter = self._treeiter_sort_to_model(treeiter)
		current = self._tv_model.iter_children(treeiter)
		while current:
			self._tv_model.remove(current)
			current = self._tv_model.iter_children(treeiter)
		self._tv_model.append(treeiter, [None, None, None, None, None, None, None])

	def signal_tv_expand_row(self, treeview, treeiter, treepath):
		treeiter = self._treeiter_sort_to_model(treeiter)
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
			self.create_model_entry(self.path_mod.join(path, name), parent)

	def create_model_entry(self, path, parent):
		"""
		Creates a row in the directory model containing a file or directory with
		its respective name, icon, size, date, and permissions.

		:param str path: The filepath of the folder the file is in.
		:param parent: A TreeIter object pointing to the parent node.
		:param str name: The name of the file.
		"""
		basename = self.path_mod.basename(path)
		try:
			stat_info = self.stat(path)
		except (OSError, IOError):
			icon = Gtk.IconTheme.get_default().load_icon('emblem-unreadable', 13, 0)
			self._tv_model.append(parent, [basename, icon, path, None, None, None, None])
			return
		perm = self._format_perm(stat_info.st_mode)
		date = datetime.datetime.fromtimestamp(stat_info.st_mtime)
		date_modified = utilities.format_datetime(date)
		if stat.S_ISDIR(stat_info.st_mode):
			icon = Gtk.IconTheme.get_default().load_icon('folder', 20, 0)
			current = self._tv_model.append(parent, (basename, icon, path, perm, None, -1, date_modified))
			self._tv_model.append(current, [None, None, None, None, None, None, None])
		else:
			file_size = self.get_file_size(path)
			hr_file_size = boltons.strutils.bytes2human(file_size)
			icon = Gtk.IconTheme.get_default().load_icon('text-x-preview', 12.5, 0)
			self._tv_model.append(parent, (basename, icon, path, perm, hr_file_size, file_size, date_modified))

	def signal_menu_activate_collapse_all(self, _):
		self.treeview.collapse_all()

	def refresh(self, treeiter=None):
		"""
		Updates the model to reflect additions and removals from other commands.
		"""
		model = self._tv_model
		if treeiter is None:
			parent_treeiter = None
			parent_path = self.cwd
			treeiter = model.get_iter_first()
		else:
			parent_treeiter = treeiter
			parent_path = model[parent_treeiter][2]
			treeiter = model.iter_children(treeiter)
		self._refresh(treeiter, parent_treeiter, parent_path)

	def _refresh(self, treeiter, parent_treeiter, parent_path):
		model = self._tv_model
		tv_model = self.treeview.get_model()
		dir_list = [self.path_mod.join(parent_path, name) for name in self._yield_dir_list(parent_path)]
		next_treeiter = treeiter
		while next_treeiter:
			treeiter = next_treeiter
			next_treeiter = model.iter_next(treeiter)
			row = model[treeiter]
			path = row[2]
			if path not in dir_list:
				model.remove(treeiter)
				continue
			path_is_dir = stat.S_ISDIR(self.path_mode(path))
			if path_is_dir ^ model.iter_has_child(treeiter):
				model.remove(treeiter)
				continue
			dir_list.remove(path)
			if path_is_dir and model.iter_has_child(treeiter):
				tv_treeiter = self._treeiter_model_to_sort(treeiter)
				if tv_treeiter and self.treeview.row_expanded(tv_model.get_path(tv_treeiter)):
					self._refresh(model.iter_children(treeiter), treeiter, path)
		for path in dir_list:
			self.create_model_entry(path, parent_treeiter)

	def signal_menu_activate_create_folder(self, _):
		selection = self.treeview.get_selection()
		_, treeiter = selection.get_selected()
		if treeiter is None:
			current = self._tv_model.append(treeiter, [' ', None, None, None, None, None, None])
			self.rename(current)
			return
		treeiter = self._treeiter_sort_to_model(treeiter)
		path = self._tv_model.get_path(treeiter)
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

	def signal_text_edited(self, renderer, treepath, text):
		treepath = self._treepath_sort_to_model(treepath)
		treeiter = self._tv_model.get_iter(treepath)
		parent = self._tv_model.iter_parent(treeiter)
		if parent is None:
			new_path = self.path_mod.join(self.cwd, text)
		else:
			new_path = self.path_mod.join(self._tv_model[parent][2], text)
		if not text or text == self._tv_model[treeiter][0]:
			return
		if stat.S_ISDIR(self.path_mode(new_path)):
			gui_utilities.show_dialog_error('Unable to make directory', self.application.get_active_window(), "Directory: {0} already exists".format(new_path))
			return
		if self._tv_model[treeiter][2] is not None:
			try:
				self._rename_file(treeiter, new_path)
			except (OSError, IOError):
				gui_utilities.show_dialog_error('Error', self.application.get_active_window(), 'Error renaming file')
		else:
			self._tv_model.remove(treeiter)
			try:
				self.make_dir(new_path)
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
	root_directory = os.path.abspath(os.sep)
	transfer_direction = 'upload'
	treeview_name = 'treeview_local'
	working_directory_combobox_name = 'comboboxtext_local_working_directory'
	def __init__(self, builder, application, config):
		self.stat = os.stat
		self._chdir = os.chdir
		self.path_mod = os.path
		self.default_directory = self.path_mod.expanduser('~')
		local_directories = config['directories'].get('local', {})
		wd_history = local_directories.get('history', [])
		super(LocalDirectory, self).__init__(builder, application, config, wd_history)
		current_directory = local_directories.get('current')
		if current_directory is None or not os.access(current_directory, os.R_OK):
			current_directory = self.default_directory
		self.change_cwd(current_directory)

	def _yield_dir_list(self, path):
		for name in os.listdir(path):
			yield name

	def path_mode(self, path):
		if not self.path_mod.exists(path):
			return 0
		return stat.S_IFMT(self.stat(path).st_mode)

	def _rename_file(self, _iter, path):
		os.rename(self._tv_model[_iter][2], path)  # pylint: disable=unsubscriptable-object

	def change_cwd(self, new_dir):
		new_dir = super(LocalDirectory, self).change_cwd(new_dir)
		if new_dir is not None:
			logger.debug('set the local working directory to: ' + new_dir)
		return new_dir

	def make_dir(self, path):
		os.makedirs(path)

	def path_is_hidden(self, path):
		if its.on_windows:
			attribute = win32api.GetFileAttributes(path)
			if attribute & (win32con.FILE_ATTRIBUTE_HIDDEN | win32con.FILE_ATTRIBUTE_SYSTEM):
				return True
		elif self.path_mod.basename(path).startswith('.'):
			return True
		return False

	@handle_permission_denied
	def delete(self, treeiter):
		"""
		Delete the selected file or directory.

		:param treeiter: The TreeIter that points to the selected file.
		"""
		row = self._tv_model[treeiter]
		if row[5] == -1:
			shutil.rmtree(row[2])
		else:
			os.remove(row[2])
		self._tv_model.remove(treeiter)
		logger.info("deleted {0}: {1}".format(('directory' if self._tv_model[treeiter][5] == -1 else 'file'), row[2])

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

	def walk(self, path):
		"""
		Walk through a given directory and return all subdirectories and
		subfiles in a format parsed for transfer. This traverses the path in a
		top-down pattern.

		:param str path: The directory to be traversed through.
		:return: A list of :py:class:`DirectoryContents` instances representing the contents.
		:rtype: list
		"""
		contents = []
		path = self.get_abspath(path)
		for walker in os.walk(path):
			contents.append(DirectoryContents(*walker))
		return contents

class RemoteDirectory(DirectoryBase):
	"""
	Remote Directory object that defines private methods for rendering remote
	data using Paramiko's SFTP functionality.
	"""
	root_directory = posixpath.abspath(posixpath.sep)
	transfer_direction = 'download'
	treeview_name = 'treeview_remote'
	working_directory_combobox_name = 'comboboxtext_remote_working_directory'
	def __init__(self, builder, application, config, ssh):
		self.ssh = ssh
		self.path_mod = posixpath
		wd_history = config['directories'].get('remote', {})
		wd_history = wd_history.get(application.config['server'].split(':', 1)[0], [])
		self._thread_local_ftp = {}
		super(RemoteDirectory, self).__init__(builder, application, config, wd_history)

		self.default_directory = application.config['server_config']['server.web_root']
		try:
			self.change_cwd(self.default_directory)
		except (IOError, OSError):
			logger.info('failed to set remote directory to the web root: ' + application.config['server_config']['server.web_root'])
			self.default_directory = self.root_directory
			self.change_cwd(self.default_directory)

	def _chdir(self, path):
		for obj_lock in self._thread_local_ftp.values():
			with obj_lock.lock:
				obj_lock.object.chdir(path)
		return

	# todo: should this be rename_path?
	def _rename_file(self, _iter, path):
		with self.ftp_handle() as ftp:
			ftp.rename(self._tv_model[_iter][2], path)  # pylint: disable=unsubscriptable-object

	def _yield_dir_list(self, path):
		with self.ftp_handle() as ftp:
			for name in ftp.listdir(path):
				yield name

	def change_cwd(self, new_dir):
		new_dir = super(RemoteDirectory, self).change_cwd(new_dir)
		if new_dir is not None:
			logger.debug('set the remote working directory to: ' + new_dir)
		return new_dir

	def make_dir(self, path):
		with self.ftp_handle() as ftp:
			ftp.mkdir(path)

	def path_is_hidden(self, path):
		if self.path_mod.basename(path).startswith('.'):
			return True
		return False

	@handle_permission_denied
	def delete(self, treeiter):
		"""
		Delete the selected file or directory.

		:param treeiter: The TreeIter that points to the selected file.
		"""
		name = self._tv_model[treeiter][2]  # pylint: disable=unsubscriptable-object
		if self.get_is_folder(name):
			if not self.remove_by_folder_name(name):
				return
		elif not self.remove_by_file_name(name):
			return
		self._tv_model.remove(treeiter)

	def ftp_acquire(self):
		"""
		Get a thread-specific ftp handle. This handle must not be transferred to
		another thread and it must be closed with a follow up call to
		:py:meth:`.ftp_release` when it is no longer needed.

		:return: A handle to an FTP session.
		"""
		current_tid = threading.current_thread().ident
		if current_tid not in self._thread_local_ftp:
			logger.info("opening a new sftp session for tid 0x{0:x}".format(current_tid))
			ftp = self.ssh.open_sftp()
			ftp.chdir(self.cwd)
			self._thread_local_ftp[current_tid] = ObjectLock(ftp, threading.RLock())
		else:
			logger.debug("leasing an existing sftp session to tid 0x{0:x}".format(current_tid))
		obj_lock = self._thread_local_ftp[current_tid]
		obj_lock.lock.acquire()
		return obj_lock.object

	@contextlib.contextmanager
	def ftp_handle(self):
		ftp = self.ftp_acquire()
		try:
			yield ftp
		finally:
			self.ftp_release()

	def ftp_release(self):
		"""
		Return a thread-specific ftp handle previously acquired with
		:py:meth:`.ftp_acquire`.
		"""
		current_tid = threading.current_thread().ident
		if current_tid not in self._thread_local_ftp:
			raise RuntimeError('ftp_release() called for thread before ftp_acquire')
		self._thread_local_ftp[current_tid].lock.release()
		logger.debug("leased sftp session released from tid 0x{0:x}".format(current_tid))
		return

	def path_mode(self, path):
		try:
			with self.ftp_handle() as ftp:
				return stat.S_IFMT(ftp.stat(path).st_mode)
		except IOError as error:
			if error.errno in (errno.ENOENT, errno.EACCES):
				return 0
			raise

	def shutdown(self):
		active_tids = tuple(self._thread_local_ftp.keys())
		logger.info("closing {0} active sftp sessions".format(len(active_tids)))
		for idx, tid in enumerate(active_tids, 1):
			obj_lock = self._thread_local_ftp[tid]
			logger.debug("closing sftp session {0} of {1} for tid 0x{2:x}".format(idx, len(active_tids), tid))
			with obj_lock.lock:
				obj_lock.object.close()
				del self._thread_local_ftp[tid]
		logger.debug('all open sftp sessions have been closed')

	def stat(self, path):
		with self.ftp_handle() as ftp:
			return ftp.stat(path)

	@handle_permission_denied
	def remove_by_folder_name(self, name):
		"""
		Removes a folder given its absolute path.

		:param name: The path of the folder to be removed.
		"""
		# with paramiko, you cannot remove populated dir, so recursive method utilized
		for path in self._yield_dir_list(name):
			new_path = self.path_mod.join(name, path)
			if self.get_is_folder(new_path):
				self.remove_by_folder_name(new_path)
			else:
				self.remove_by_file_name(new_path)
		with self.ftp_handle() as ftp:
			ftp.rmdir(name)

	@handle_permission_denied
	def remove_by_file_name(self, name):
		"""
		Removes a file given its absolute path.

		:param name: The path of the file to be removed.
		"""
		with self.ftp_handle() as ftp:
			ftp.remove(name)

	def walk(self, path):
		"""
		Walk through a given directory and return all subdirectories and
		subfiles in a format parsed for transfer. This traverses the path in a
		top-down pattern.

		:param str path: The directory to be traversed through.
		:return: A list of :py:class:`DirectoryContents` instances representing the contents.
		:rtype: list
		"""
		contents = []
		path = self.get_abspath(path)
		subdirs = []
		files = []
		try:
			entries = list(self._yield_dir_list(path))
		except (IOError, OSError):
			return contents
		for entry in entries:
			if self.get_is_folder(self.path_mod.join(path, entry)):
				subdirs.append(entry)
			else:
				files.append(entry)
		contents.append(DirectoryContents(path, subdirs, files))
		for folder in subdirs:
			contents.extend(self.walk(self.path_mod.join(path, folder)))
		return contents

class FileManager(object):
	"""
	File manager that manages the Transfer Queue by adding new tasks and
	handling tasks put in, as well as handles communication between all the
	other classes.
	"""
	def __init__(self, application, ssh, config):
		self.application = application
		self.config = config
		self.queue = TaskQueue()
		self._threads = []
		self._threads_max = 1
		self._threads_shutdown = threading.Event()
		for _ in range(self._threads_max):
			thread = threading.Thread(target=self._thread_routine)
			thread.start()
			self._threads.append(thread)
		self.builder = Gtk.Builder()
		self.builder.add_from_file(gtk_builder_file)
		self.window = self.builder.get_object('SFTPClientGUI.window')
		self.status_display = StatusDisplay(self.builder, self.queue)
		self.local = LocalDirectory(self.builder, self.application, config)
		self.remote = RemoteDirectory(self.builder, self.application, config, ssh)
		self.builder.get_object('button_upload').connect('button-press-event', lambda widget, event: self._queue_transfer_from_selection(UploadTask))
		self.builder.get_object('button_download').connect('button-press-event', lambda widget, event: self._queue_transfer_from_selection(DownloadTask))
		self.local.menu_item_transfer.connect('activate', lambda widget: self._queue_transfer_from_selection(UploadTask))
		self.remote.menu_item_transfer.connect('activate', lambda widget: self._queue_transfer_from_selection(DownloadTask))
		menu_item = self.builder.get_object('menuitem_opts_transfer_hidden')
		menu_item.set_active(self.config['transfer_hidden'])
		menu_item.connect('toggled', self.signal_toggled_config_option, 'transfer_hidden')
		menu_item = self.builder.get_object('menuitem_opts_show_hidden')
		menu_item.set_active(self.config['show_hidden'])
		menu_item.connect('toggled', self.signal_toggled_config_option_show_hidden)
		menu_item = self.builder.get_object('menuitem_exit')
		menu_item.connect('activate', lambda _: self.window.destroy())
		self.window.connect('destroy', self.signal_window_destroy)
		self.window.show_all()

	def signal_toggled_config_option(self, menuitem, config_key):
		self.config[config_key] = menuitem.get_active()

	def signal_toggled_config_option_show_hidden(self, menuitem):
		self.config['show_hidden'] = menuitem.get_active()
		self.local.refilter()
		self.remote.refilter()

	def _transfer_dir(self, task):
		task.state = 'Transferring'
		if isinstance(task, DownloadTask):
			dst, dst_path = self.local, task.local_path
		elif isinstance(task, UploadTask):
			dst, dst_path = self.remote, task.remote_path
		else:
			raise ValueError('task_cls must be a subclass of TransferTask')
		if not stat.S_ISDIR(dst.path_mode(dst_path)):
			dst.make_dir(dst_path)

		if not task.size:
			task.state = 'Completed'

	def _transfer_file(self, task, chunk=0x1000):
		task.state = 'Transferring'
		self.status_display.sync_view(task)
		ftp = self.remote.ftp_acquire()
		write_mode = 'ab+' if task.transferred > 0 else 'wb+'
		if isinstance(task, UploadTask):
			src_file_h = open(task.local_path, 'rb')
			dst_file_h = ftp.file(task.remote_path, write_mode)
		elif isinstance(task, DownloadTask):
			src_file_h = ftp.file(task.remote_path, 'rb')
			dst_file_h = open(task.local_path, write_mode)
		else:
			self.remote.ftp_release()
			raise ValueError('unsupported task type passed to _transfer_file')
		self.remote.ftp_release()
		src_file_h.seek(task.transferred)
		try:
			while task.transferred < task.size:
				if self._threads_shutdown.is_set():
					task.state = 'Cancelled'
				if task.state != 'Transferring':
					break
				temp = src_file_h.read(chunk)
				dst_file_h.write(temp)
				task.transferred += chunk
				self.status_display.sync_view(task)
		except Exception as error:
			raise error
		finally:
			src_file_h.close()
			dst_file_h.close()
		if task.state == 'Cancelled':
			if isinstance(task, UploadTask):
				self.remote.remove_by_file_name(task.remote_path)
			elif isinstance(task, DownloadTask):
				self.local.remove_by_file_name(task.local_path)
		elif task.state != 'Paused':
			task.state = 'Completed'
			GLib.idle_add(self._idle_refresh_directories)

	def _idle_refresh_directories(self):
		self.local.refresh()
		self.remote.refresh()

	def _thread_routine(self):
		while not self._threads_shutdown.is_set():
			task = self.queue.get()
			if isinstance(task, ShutdownTask):
				logger.info('processing task: ' + str(task))
				task.state = 'Completed'
				self.queue.remove(task)
				break
			elif isinstance(task, TransferTask):
				logger.debug('processing task: ' + str(task))
				try:
					if isinstance(task, TransferDirectoryTask):
						self._transfer_dir(task)
					else:
						self._transfer_file(task)
				except Exception:
					logger.error("unknown error processing task: {0!r}".format(task), exc_info=True)
					if not task.is_done:
						task.state = 'Error'
						for parent in task.parents:
							parent.state = 'Error'
				self.status_display.sync_view([task] + task.parents)

	def signal_window_destroy(self, _):
		self.window.set_sensitive(False)
		self._threads_shutdown.set()
		for _ in self._threads:
			self.queue.put(ShutdownTask())
		for thread in self._threads:
			thread.join()
		self.local.shutdown()
		self.remote.shutdown()
		directories = self.config.get('directories', {})
		directories['local'] = {
			'current': self.local.cwd,
			'history': list(self.local.wd_history)
		}
		if 'remote' not in directories:
			directories['remote'] = {}
		directories['remote'][self.application.config['server'].split(':', 1)[0]] = list(self.remote.wd_history)
		self.config['directories'] = directories

	def _queue_transfer_from_selection(self, task_cls):
		selection = self.local.treeview.get_selection()
		model, treeiter = selection.get_selected()
		local_path = self.local.cwd if treeiter is None else model[treeiter][2]

		selection = self.remote.treeview.get_selection()
		model, treeiter = selection.get_selected()
		remote_path = self.remote.cwd if treeiter is None else model[treeiter][2]

		if issubclass(task_cls, DownloadTask):
			src_path, dst_path = remote_path, local_path
		elif issubclass(task_cls, UploadTask):
			src_path, dst_path = local_path, remote_path
		else:
			raise ValueError('task_cls must be a subclass of TransferTask')
		self.queue_transfer(task_cls, src_path, dst_path)

	def queue_transfer(self, task_cls, src_path, dst_path):
		if issubclass(task_cls, DownloadTask):
			src, dst = self.remote, self.local
		elif issubclass(task_cls, UploadTask):
			src, dst = self.local, self.remote
		else:
			raise ValueError('task_cls must be a subclass of TransferTask')
		if dst.get_is_folder(dst_path):
			dst_path = dst.path_mod.join(dst_path, src.path_mod.basename(src_path))
		if src.get_is_folder(src_path):
			self._queue_dir_transfer(task_cls, src_path, dst_path)
		else:
			self._queue_file_transfer(task_cls, src_path, dst_path)

	def _queue_file_transfer(self, task_cls, src_path, dst_path):
		"""
		Handles the file transfer by stopping bad transfers, creating tasks for
		transfers, and placing them in the queue.

		:param task_cls: The type of task the transfer will be.
		:param str src_path: The source path to be uploaded or downloaded.
		:param str dst_path: The destination path to be created and data transferred into.
		"""
		if issubclass(task_cls, DownloadTask):
			if not os.access(os.path.dirname(dst_path), os.W_OK):
				gui_utilities.show_dialog_error(
					'Permission Denied',
					self.application.get_active_window(),
					'Cannot write to the destination folder.'
				)
				return
			local_path, remote_path = self.local.get_abspath(dst_path), self.remote.get_abspath(src_path)
		elif issubclass(task_cls, UploadTask):
			if not os.access(src_path, os.R_OK):
				gui_utilities.show_dialog_error(
					'Permission Denied',
					self.application.get_active_window(),
					'Cannot read the source file.'
				)
				return
			local_path, remote_path = self.local.get_abspath(src_path), self.remote.get_abspath(dst_path)
		file_task = task_cls(local_path, remote_path)
		if isinstance(file_task, UploadTask):
			file_size = self.local.get_file_size(local_path)
		elif isinstance(file_task, DownloadTask):
			file_size = self.remote.get_file_size(remote_path)
		file_task.size = file_size
		self.queue.put(file_task)
		self.status_display.sync_view(file_task)

	def _queue_dir_transfer(self, task_cls, src_path, dst_path):
		"""
		Handles the folder transfer by stopping bad transfers, creating tasks
		for transfers, and placing them in the queue.

		:param task_cls: The type of task the transfer will be.
		:param str src_path: The path to be uploaded or downloaded.
		:param str dst_path: The path to be created.
		"""
		if issubclass(task_cls, DownloadTask):
			src, dst = self.remote, self.local
			if not os.access(dst.path_mod.dirname(dst_path), os.W_OK):
				gui_utilities.show_dialog_error('Permission Denied', self.application.get_active_window(), 'Can not write to the destination directory.')
				return
			task = task_cls.dir_cls(dst_path, src_path, size=0)
		elif issubclass(task_cls, UploadTask):
			if not os.access(src_path, os.R_OK):
				gui_utilities.show_dialog_error('Permission Denied', self.application.get_active_window(), 'Can not read the source directory.')
				return
			src, dst = self.local, self.remote
			task = task_cls.dir_cls(src_path, dst_path, size=0)
			if not stat.S_ISDIR(dst.path_mode(dst_path)):
				try:
					dst.make_dir(dst_path)
				except (IOError, OSError):
					gui_utilities.show_dialog_error('Permission Denied', self.application.get_active_window(), 'Can not create the destination directory.')
					return
		else:
			raise ValueError('unknown task class')

		queued_tasks = []
		parent_directory_tasks = collections.OrderedDict({src_path: task})

		for dir_cont in src.walk(src_path):
			dst_base_path = dst.path_mod.normpath(dst.path_mod.join(dst_path, src.get_relpath(dir_cont.dirpath, start=src_path)))
			src_base_path = dir_cont.dirpath
			parent_task = parent_directory_tasks.pop(src_base_path, None)
			if parent_task is None:
				continue
			queued_tasks.append(parent_task)

			new_task_count = 0
			if issubclass(task_cls, DownloadTask):
				local_base_path, remote_base_path = (dst_base_path, src_base_path)
			else:
				local_base_path, remote_base_path = (src_base_path, dst_base_path)

			for filename in dir_cont.filenames:
				if not self.config['transfer_hidden'] and src.path_is_hidden(src.path_mod.join(src_base_path, filename)):
					continue
				try:
					file_size = src.get_file_size(src.path_mod.join(dir_cont.dirpath, filename))
				except (IOError, OSError):
					continue  # skip this file if we can't get it's size
				task = task_cls(
					self.local.path_mod.join(local_base_path, filename),
					self.remote.path_mod.join(remote_base_path, filename),
					parent=parent_task,
					size=file_size
				)
				queued_tasks.append(task)
				new_task_count += 1

			for dirname in dir_cont.dirnames:
				if not self.config['transfer_hidden'] and src.path_is_hidden(src.path_mod.join(src_base_path, dirname)):
					continue
				task = task_cls.dir_cls(
					self.local.path_mod.join(local_base_path, dirname),
					self.remote.path_mod.join(remote_base_path, dirname),
					parent=parent_task,
					size=0
				)
				parent_directory_tasks[src.path_mod.join(src_base_path, dirname)] = task
				new_task_count += 1

			parent_task.size += new_task_count
			for grandparent_task in parent_task.parents:
				grandparent_task.size += new_task_count
		for task in queued_tasks:
			self.queue.put(task)
		self.status_display.sync_view(queued_tasks)
