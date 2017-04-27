import collections
import logging
import os
import stat
import threading

import boltons.strutils
import boltons.timeutils

from . import tasks
from . import directory
from . import sftp_utilities
from . import editor

from king_phisher.client import gui_utilities

from gi.repository import Gtk
from gi.repository import Gdk
from gi.repository import GdkPixbuf
from gi.repository import GLib

#gtk_builder_file = os.path.splitext(__file__)[0] + '.ui'
logger = logging.getLogger('KingPhisher.Plugins.SFTPClient')

class StatusDisplay(object):
	"""
	Class representing the bottom treeview of the GUI. This contains the logging
	and graphical representation of all queued transfers.
	"""
	def __init__(self, queue):
		self.queue = queue
		self.scroll = sftp_utilities.get_object('SFTPClient.notebook.page_stfp.scrolledwindow_transfer_statuses')
		self.treeview_transfer = sftp_utilities.get_object('SFTPClient.notebook.page_stfp.treeview_transfer_statuses')
		self._tv_lock = threading.RLock()

		col_text = Gtk.CellRendererText()
		col_img = Gtk.CellRendererPixbuf()
		col = Gtk.TreeViewColumn('')
		col.pack_start(col_img, False)
		col.add_attribute(col_img, 'pixbuf', 0)
		self.treeview_transfer.append_column(col)

		self.treeview_transfer.append_column(sftp_utilities.get_treeview_column('Local File', col_text, 1, m_col_sort=1, resizable=True))
		self.treeview_transfer.append_column(sftp_utilities.get_treeview_column('Remote File', col_text, 2, m_col_sort=2, resizable=True))
		self.treeview_transfer.append_column(sftp_utilities.get_treeview_column('Status', col_text, 3, m_col_sort=3, resizable=True))

		col_bar = Gtk.TreeViewColumn('Progress')
		progress = Gtk.CellRendererProgress()
		col_bar.pack_start(progress, True)
		col_bar.add_attribute(progress, 'value', 4)
		col_bar.set_property('resizable', True)
		col_bar.set_min_width(125)
		self.treeview_transfer.append_column(col_bar)

		self.treeview_transfer.append_column(sftp_utilities.get_treeview_column('Size', col_text, 5, m_col_sort=3, resizable=True))
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

	def _sync_view(self, sftp_tasks=None):
		# This value was set to True to prevent the treeview from freezing.
		if not self.queue.mutex.acquire(blocking=True):
			return
		if not self._tv_lock.acquire(blocking=False):
			self.queue.mutex.release()
			return
		sftp_tasks = (sftp_tasks or self.queue.queue)
		for task in sftp_tasks:
			if not isinstance(task, tasks.TransferTask):
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
					None if (task.size is None or isinstance(task, tasks.TransferDirectoryTask)) else boltons.strutils.bytes2human(task.size),
					task
				])
				task.treerowref = Gtk.TreeRowReference.new(self._tv_model, self._tv_model.get_path(treeiter))
			elif task.treerowref.valid():
				row = self._tv_model[task.treerowref.get_path()]  # pylint: disable=unsubscriptable-object
				row[3] = task.state
				row[4] = task.progress
		self.queue.mutex.release()
		return False

	def sync_view(self, sftp_tasks=None):
		if isinstance(sftp_tasks, tasks.Task):
			sftp_tasks = (sftp_tasks,)
		GLib.idle_add(self._sync_view, sftp_tasks, priority=GLib.PRIORITY_DEFAULT_IDLE)

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

class FileManager(object):
	"""
	File manager that manages the Transfer Queue by adding new tasks and
	handling tasks put in, as well as handles communication between all the
	other classes.
	"""
	def __init__(self, application, ssh, config):
		self.application = application
		self.config = config
		self.queue = tasks.TaskQueue()
		self._threads = []
		self._threads_max = 1
		self._threads_shutdown = threading.Event()
		for _ in range(self._threads_max):
			thread = threading.Thread(target=self._thread_routine)
			thread.start()
			self._threads.append(thread)
		self.editor = None
		self.window = sftp_utilities.get_object('SFTPClient.window')
		self.notebook = sftp_utilities.get_object('SFTPClient.notebook')
		self.editor_tab_save_button = sftp_utilities.get_object('SFTPClient.notebook.page_editor.toolbutton_save_html_file')
		self.editor_tab_save_button.set_sensitive(False)
		self.editor_tab_save_button.connect('clicked', self.signal_editor_save)
		self.status_display = StatusDisplay(self.queue)
		self.local = directory.LocalDirectory(self.application, config)
		self.remote = directory.RemoteDirectory(self.application, config, ssh)
		sftp_utilities.get_object('SFTPClient.notebook.page_stfp.button_upload').connect('button-press-event', lambda widget, event: self._queue_transfer_from_selection(tasks.UploadTask))
		sftp_utilities.get_object('SFTPClient.notebook.page_stfp.button_download').connect('button-press-event', lambda widget, event: self._queue_transfer_from_selection(tasks.DownloadTask))
		self.local.menu_item_transfer.connect('activate', lambda widget: self._queue_transfer_from_selection(tasks.UploadTask))
		self.remote.menu_item_transfer.connect('activate', lambda widget: self._queue_transfer_from_selection(tasks.DownloadTask))
		self.local.menu_item_edit.connect('activate', self.signal_edit_local_file)
		self.remote.menu_item_edit.connect('activate', self.signal_edit_remote_file)
		menu_item = sftp_utilities.get_object('SFTPClient.notebook.page_stfp.menuitem_opts_transfer_hidden')
		menu_item.set_active(self.config['transfer_hidden'])
		menu_item.connect('toggled', self.signal_toggled_config_option, 'transfer_hidden')
		menu_item = sftp_utilities.get_object('SFTPClient.notebook.page_stfp.menuitem_opts_show_hidden')
		menu_item.set_active(self.config['show_hidden'])
		menu_item.connect('toggled', self.signal_toggled_config_option_show_hidden)
		menu_item = sftp_utilities.get_object('SFTPClient.notebook.page_stfp.menuitem_exit')
		menu_item.connect('activate', lambda _: self.window.destroy())
		self.window.connect('destroy', self.signal_window_destroy)
		self.window.show_all()

	def signal_edit_local_file(self, _):
		selection = self.local.treeview.get_selection()
		model, treeiter = selection.get_selected()
		local_file_path = self.local.get_abspath(model[treeiter][2])
		try:
			file_contents = self.local.read_file(local_file_path)
		except ValueError:
			logger.warning("cannot read file {}".format(local_file_path))
			gui_utilities.show_dialog_error(
				'Permission Denied',
				self.application.get_active_window(),
				'Cannot read to the file.'
			)
			return
		self.editor = editor.SftpEditor(file_contents, local_file_path, 'local')

	def signal_edit_remote_file(self, _):
		selection = self.remote.treeview.get_selection()
		model, treeiter = selection.get_selected()
		remote_file_path = self.remote.get_abspath(model[treeiter][2])
		try:
			file_contents = self.remote.ftp_read_file(remote_file_path)
			print(type(file_contents))
		except IOError:
			logger.warning("cannot read remote file {}".format(remote_file_path))
			gui_utilities.show_dialog_error(
				'Permission Denied',
				self.application.get_active_window(),
				'Cannot read remote file'
			)
			return
		print("Type of file contents going into editor {}".format(type(file_contents)))
		self.editor = editor.SftpEditor(file_contents, remote_file_path, 'remote')

	def signal_editor_save(self, _):
		self._save_editor_file()

	def signal_toggled_config_option(self, menuitem, config_key):
		self.config[config_key] = menuitem.get_active()

	def signal_toggled_config_option_show_hidden(self, menuitem):
		self.config['show_hidden'] = menuitem.get_active()
		self.local.refilter()
		self.remote.refilter()

	def _save_editor_file(self):
		if not self.editor:
			self.editor_tab_save_button.set_sensitive(False)
			return

		buffer_contents = self.editor.sourceview_buffer.get_text(
			self.editor.sourceview_buffer.get_start_iter(),
			self.editor.sourceview_buffer.get_end_iter(),
			False
		)
		if buffer_contents == self.editor.file_contents:
			logger.info('no changes found in file')
			return

		if self.editor.location == 'local':
			if not (self.editor.file_path and os.path.isfile(self.editor.file_path) and os.access(self.editor.file_path, os.W_OK)):
				self.editor_tab_save_button.set_sensitive(False)
				gui_utilities.show_dialog_error(
					'Permission Denied',
					self.application.get_active_window(),
					'Cannot write to local file'
				)
			file = open(self.editor.file_path, 'w')
			file.write(buffer_contents)
			file.close()
			self.editor.file_contents = buffer_contents
			logger.info('saved edited to file {}'.format(self.editor.file_path))
			return
		elif self.editor.location == 'remote':
			try:
				self.remote.ftp_save_file(self.editor.file_path, buffer_contents)
				self.editor.file_contents = buffer_contents
			except IOError:
				self.editor_tab_save_button.set_sensitive(False)
				gui_utilities.show_dialog_error(
					'Permission Denied',
					self.application.get_active_window(),
					'Cannot write to remote file'
				)

	def _transfer_dir(self, task):
		task.state = 'Transferring'
		if isinstance(task, tasks.DownloadTask):
			dst, dst_path = self.local, task.local_path
		elif isinstance(task, tasks.UploadTask):
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
		if isinstance(task, tasks.UploadTask):
			src_file_h = open(task.local_path, 'rb')
			dst_file_h = ftp.file(task.remote_path, write_mode)
		elif isinstance(task, tasks.DownloadTask):
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
			if isinstance(task, tasks.UploadTask):
				self.remote.remove_by_file_name(task.remote_path)
			elif isinstance(task, tasks.DownloadTask):
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
			if isinstance(task, tasks.ShutdownTask):
				logger.info('processing task: ' + str(task))
				task.state = 'Completed'
				self.queue.remove(task)
				break
			elif isinstance(task, tasks.TransferTask):
				logger.debug('processing task: ' + str(task))
				try:
					if isinstance(task, tasks.TransferDirectoryTask):
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
			self.queue.put(tasks.ShutdownTask())
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
		sftp_utilities._gtk_objects = {}

	def _queue_transfer_from_selection(self, task_cls):
		selection = self.local.treeview.get_selection()
		model, treeiter = selection.get_selected()
		local_path = self.local.cwd if treeiter is None else model[treeiter][2]

		selection = self.remote.treeview.get_selection()
		model, treeiter = selection.get_selected()
		remote_path = self.remote.cwd if treeiter is None else model[treeiter][2]

		if issubclass(task_cls, tasks.DownloadTask):
			src_path, dst_path = remote_path, local_path
		elif issubclass(task_cls, tasks.UploadTask):
			src_path, dst_path = local_path, remote_path
		else:
			raise ValueError('task_cls must be a subclass of TransferTask')
		self.queue_transfer(task_cls, src_path, dst_path)

	def queue_transfer(self, task_cls, src_path, dst_path):
		if issubclass(task_cls, tasks.DownloadTask):
			src, dst = self.remote, self.local
		elif issubclass(task_cls, tasks.UploadTask):
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
		if issubclass(task_cls, tasks.DownloadTask):
			if not os.access(os.path.dirname(dst_path), os.W_OK):
				gui_utilities.show_dialog_error(
					'Permission Denied',
					self.application.get_active_window(),
					'Cannot write to the destination folder.'
				)
				return
			local_path, remote_path = self.local.get_abspath(dst_path), self.remote.get_abspath(src_path)
		elif issubclass(task_cls, tasks.UploadTask):
			if not os.access(src_path, os.R_OK):
				gui_utilities.show_dialog_error(
					'Permission Denied',
					self.application.get_active_window(),
					'Cannot read the source file.'
				)
				return
			local_path, remote_path = self.local.get_abspath(src_path), self.remote.get_abspath(dst_path)
		file_task = task_cls(local_path, remote_path)
		if isinstance(file_task, tasks.UploadTask):
			file_size = self.local.get_file_size(local_path)
		elif isinstance(file_task, tasks.DownloadTask):
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
		if issubclass(task_cls, tasks.DownloadTask):
			src, dst = self.remote, self.local
			if not os.access(dst.path_mod.dirname(dst_path), os.W_OK):
				gui_utilities.show_dialog_error('Permission Denied', self.application.get_active_window(), 'Can not write to the destination directory.')
				return
			task = task_cls.dir_cls(dst_path, src_path, size=0)
		elif issubclass(task_cls, tasks.UploadTask):
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
			if issubclass(task_cls, tasks.DownloadTask):
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
