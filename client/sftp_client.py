import os
import datetime
import stat
import shutil
import time

import threading
import Queue

import king_phisher.client.plugins as plugins
from king_phisher import utilities
from king_phisher.client import gui_utilities
from king_phisher import its

import boltons.strutils
import boltons.timeutils
from gi.repository import Gtk
from gi.repository import Gdk
from gi.repository import GdkPixbuf
from gi.repository import GObject
from gi.repository import GLib

if its.py_v2:
	import Queue as queue
else:
	import queue

GTYPE_LONG = GObject.type_from_name('glong')

def get_treeview_column(name, renderer, m_col, m_col_sort=None):
	tv_col = Gtk.TreeViewColumn(name)
	tv_col.pack_start(renderer, True)
	tv_col.add_attribute(renderer, 'text', m_col)
	if m_col_sort is not None:
		tv_col.set_sort_column_id(m_col_sort)
	return tv_col

class Plugin(plugins.ClientPlugin):
	authors = ['Josh Jacob']
	title = 'SFTP Client'
	description = """
	Secure File Transfer Protocol Client that can be used to upload, download,
	create, and delete local and remote files on the King Phisher Server.
	"""
	homepage = 'https://github.com/securestate/king-phisher'
	def initialize(self):
		self.sftp_window = None
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
			target_file = os.path.splitext(__file__)[0] + '.ui'
			self.logger.debug('loading gtk builder file from: ' + target_file)
			manager = FileManager(target_file, self.application, ssh)  # pylint: disable=unused-variable
			self.sftp_window = manager.window
			self.sftp_window.connect('destroy', self.signal_window_destroy)
		self.sftp_window.show()
		self.sftp_window.present()

	def signal_window_destroy(self, window):
		self.sftp_window = None

class Logger(object):
	def __init__(self, builder, *args, **kwargs):
		self.builder = builder
		self.scroll = self.builder.get_object('logger_scroll')
		self.treeview_transfer = self.builder.get_object('SFTPClientGUI.treeview_transfer')
		self.progress_bar = self.builder.get_object('SFTPClientGUI.progressbar')
		self.label_file = self.builder.get_object('SFTPClientGUI.label')
		col_text = Gtk.CellRendererText()
		columns = ('Direction', 'Source', 'Destination', 'Status')

		col = get_treeview_column('Direction', col_text, 0, m_col_sort=0)
		col_src = get_treeview_column('Source', col_text, 1, m_col_sort=1)
		col_dest = get_treeview_column('Destination', col_text, 2, m_col_sort=2)
		col_stat = get_treeview_column('Status', col_text, 3, m_col_sort=3)

		col_bar = Gtk.TreeViewColumn('Progress')
		progress = Gtk.CellRendererProgress()
		col_bar.pack_start(progress, True)
		col_bar.add_attribute(progress, 'value', 4)

		self.id_to_event = {}
		self.counter = 0
		for column in [col, col_src, col_dest, col_stat, col_bar]:
			self.treeview_transfer.append_column(column)
		self._tv_model = Gtk.ListStore(str, str, str, str, int)
		self.treeview_transfer.connect('size-allocate', self.signal_tv_size_allocate)
		self.treeview_transfer.connect('button_press_event', self.signal_tv_button_pressed)
		self.treeview_transfer.set_model(self._tv_model)

		self.treeview_transfer.show_all()

		self.popup_menu = Gtk.Menu.new()
		menu_item = Gtk.MenuItem.new_with_label('Clear')
		menu_item.connect('activate', self.signal_menu_activate_clear)
		self.popup_menu.append(menu_item)
		self.popup_menu.show_all()

	def signal_menu_activate_clear(self, _):
		self._tv_model.clear()

	def signal_tv_button_pressed(self, _, event):
		if event.button == Gdk.BUTTON_SECONDARY:
			self.popup_menu.popup(None, None, None, None, event.button, Gtk.get_current_event_time())
			return True
		return

	def signal_tv_size_allocate(self, widget, event, data=None):
		adj = self.scroll.get_vadjustment()
		adj.set_value(0)

	def log_transfer(self, direction, src, dest, stat, bar):
		return self._tv_model.prepend([direction, src, dest, stat, bar])

class DirectoryBase(object):
	def __init__(self, treeview, logger):
		self.logger = logger
		self.treeview = treeview
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

		col_perm = get_treeview_column('Permissions', col_text, 3, m_col_sort=3)
		col_size = get_treeview_column('Size', col_text, 4, m_col_sort=5)
		col_date = get_treeview_column('Date Modified', col_text, 6, m_col_sort=6)

		self.treeview.append_column(col)
		self.treeview.append_column(col_perm)
		self.treeview.append_column(col_size)
		self.treeview.append_column(col_date)

		self.treeview.connect('button_press_event', self.signal_tv_button_press)
		self.treeview.connect('key-press-event', self.signal_tv_key_press)
		self.treeview.connect('row-expanded', self.signal_tv_expand_row)
		self.treeview.connect('row-collapsed', self.signal_tv_collapse_row)
		self._tv_model = Gtk.TreeStore(str, GdkPixbuf.Pixbuf, str, str, str, GTYPE_LONG, str)
		self.treeview.set_model(self._tv_model)

		self.local_hidden = True
		self._get_popup_menu()

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

		label = 'Upload' if self.treeview_name == 'treeview_local' else 'Download'
		menu_item = Gtk.MenuItem.new_with_label(label)
		menu_item.connect('activate', self.signal_menu_activate_transfer)
		self.popup_menu.append(menu_item)

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
		model, treeiter = selection.get_selected()
		self.rename(treeiter)

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
			parent_name = self.def_dir
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
				time = datetime.datetime.fromtimestamp(raw_time)
				date_modified = '   ' + utilities.format_datetime(time)
				is_folder = self._get_is_folder(fullname)
			except (OSError, IOError):
				icon = Gtk.IconTheme.get_default().load_icon('emblem-unreadable', 13, 0)
				self._tv_model.append(parent, [name, icon, fullname, None, None, None, None])
				continue
			if is_folder:
				icon = Gtk.IconTheme.get_default().load_icon('folder', 20, 0)
				current = self._tv_model.append(parent, (name, icon, fullname, perm, None, -1, date_modified))
			else:
				file_size = self._get_file_size(fullname)
				hr_file_size = '   ' + boltons.strutils.bytes2human(file_size)
				icon = Gtk.IconTheme.get_default().load_icon('text-x-preview', 12.5, 0)
				current = self._tv_model.append(parent, (name, icon, fullname, perm, hr_file_size, file_size, date_modified))
			if is_folder and perm[3] == 'r' and perm[5] == 'x':
				self._tv_model.append(current, [None, None, None, None, None, None, None])

	def signal_menu_toggled_hidden_files(self, _):  # pylint: disable=method-hidden
		self.local_hidden = not self.local_hidden
		self.refresh()

	def signal_menu_activate_collapse_all(self, _):
		self.treeview.collapse_all()

	def refresh(self):
		model = self._tv_model
		exp_lines = []
		model.foreach(lambda model, path, iter: exp_lines.append(path) if self.treeview.row_expanded(path) else 0)
		self.treeview.collapse_all()
		for path in exp_lines:
			self.treeview.expand_row(path, False)

	def signal_menu_activate_transfer(self, _):
		pass

	def signal_menu_activate_create_folder(self, _):
		selection = self.treeview.get_selection()
		model, treeiter = selection.get_selected()
		fullname = model[treeiter][2]
		dir_name = 'New Folder'
		new_path = fullname + '/' + dir_name
		path = self._tv_model.get_path(treeiter)
		perm = self._check_perm(fullname)
		w_perm = True if perm[4] == 'w' else False
		if not w_perm:
			gui_utilities.show_dialog_error('Permission Denied', self.application.get_active_window(), "Cannot access {0} as user".format(fullname))
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
			new_path = self.def_dir + '/' + text
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

class LocalDirectory(DirectoryBase):
	treeview_name = 'treeview_local'
	def __init__(self, builder, logger, upload_button, application):
		self.application = application
		_treeview = builder.get_object('SFTPClientGUI.' + self.treeview_name)
		super(LocalDirectory, self).__init__(_treeview, logger)
		self.upload_button = upload_button
		self.def_dir = os.path.abspath(os.sep)
		self.load_dirs(self.def_dir)

	def _check_perm(self, fullname):
		r_permissions = os.access(fullname, os.R_OK)
		w_permissions = os.access(fullname, os.W_OK)
		x_permissions = os.access(fullname, os.X_OK)
		perm = '   '
		perm = perm + 'r' if r_permissions else perm + '-'
		perm = perm + 'w' if w_permissions else perm + '-'
		perm = perm + 'x' if x_permissions else perm + '-'
		return perm

	def _yield_dir_list(self, path):
		for name in os.listdir(path):
			yield name

	def _already_exists(self, path):
		return os.path.isdir(path)

	def _rename_file(self, _iter, path):
		os.rename(self._tv_model[_iter][2], path)

	def _make_file(self, path):
			os.makedirs(path)

	def _get_raw_time(self, fullname):
		return os.path.getmtime(fullname)

	def _get_is_folder(self, fullname):
		return stat.S_ISDIR(os.stat(fullname).st_mode)

	def _get_file_size(self, fullname):
		return os.path.getsize(fullname)

	def delete(self, model, treeiter):
		try:
			if model[treeiter][5] == -1:
				shutil.rmtree(model[treeiter][2])
			else:
				os.remove(model[treeiter][2])
		except OSError:
			gui_utilities.show_dialog_error('Permission Denied', self.application.get_active_window())
		else:
			gui_utilities.show_dialog_warning('Successfully deleted ' + model[treeiter][2], self.application.get_active_window())
			self.refresh()

class RemoteDirectory(DirectoryBase):
	treeview_name = 'treeview_remote'
	def __init__(self, builder, logger, download_button, application, ftp):
		_treeview = builder.get_object('SFTPClientGUI.' + self.treeview_name)
		super(RemoteDirectory, self).__init__(_treeview, logger)
		self.ftp = ftp
		self.download_button = download_button
		self.application = application
		self.def_dir = self.application.config['server_config']['server.web_root']
		self.load_dirs(self.def_dir)

	def _check_perm(self, fullname):
		lstatout = self.ftp.stat(fullname)
		mode = lstatout.st_mode
		perm = '   '
		perm += 'r' if bool(mode & stat.S_IROTH) else '-'
		perm += 'w' if bool(mode & stat.S_IWOTH) else '-'
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
		self.ftp.rename(self._tv_model[_iter][2], path)

	def _make_file(self, path):
		self.ftp.mkdir(path)

	def _get_raw_time(self, fullname):
		lstatout = self.ftp.stat(fullname)
		return lstatout.st_mtime

	def _get_is_folder(self, fullname):
		lstatout = self.ftp.stat(fullname)
		mode = lstatout.st_mode
		return stat.S_ISDIR(mode)

	def _get_file_size(self, fullname):
		lstatout = self.ftp.stat(fullname)
		return lstatout.st_size

	def delete(self, model, treeiter):
		try:
			if self._get_is_folder(self._tv_model[treeiter][2]):
				self.ftp.rmdir(model[treeiter][2])
			else:
				self.ftp.remove(model[treeiter][2])
		except IOError:
			gui_utilities.show_dialog_error('Permission Denied', self.application.get_active_window())
		else:
			gui_utilities.show_dialog_warning('Successfully deleted ' + model[treeiter][2], self.application.get_active_window())
			self.refresh()

class FileManager(object):
	def __init__(self, target_file, application, ssh, *args, **kwargs):
		self.application = application
		self.queue = queue.Queue()
		self.upload_wheel = []
		self._threads = []
		self._threads_max = 1
		self._threads_shutdown = threading.Event()
		for _ in range(self._threads_max):
			thread = threading.Thread(target=self._thread_routine, args=((ssh,)))
			thread.start()
			self._threads.append(thread)
		ftp = ssh.open_sftp()
		self.builder = Gtk.Builder()
		self.builder.add_from_file(target_file)
		self.window = self.builder.get_object('SFTPClientGUI.window')
		upload_button = self.builder.get_object('button_upload')
		download_button = self.builder.get_object('button_download')
		self.logger = Logger(self.builder)
		self.local = LocalDirectory(self.builder, self.logger, upload_button, self.application)  # pylint: disable=unused-variable
		self.remote = RemoteDirectory(self.builder, self.logger, download_button, self.application, ftp)  # pylint: disable=unused-variable
		self.local.upload_button.connect('button-press-event', self.upload)
		self.remote.download_button.connect('button-press-event', self.download)
		self.acceptable_perms = ('r-x', 'r--', 'rwx', 'rw-')
		self.window.connect('destroy', self.signal_window_destroy)
		self.window.show_all()

	### FIXME ###
	def _transfer(self, src, dst, ssh, direction, chunk=0x1000):
		ftp = ssh.open_sftp()
		size = self.local._get_file_size(src)
		transfered = 0
		if direction == 'U':
			file_h = open(src)
			file_r = ftp.file(dst, 'w')
		else:
			file_h = ftp.file(src, 'r')
			file_r = open(dst, 'a')
		while not self._threads_shutdown.is_set() and transfered < size:
			GLib.idle_add(self._idle_update_status, transfered, size)
			temp = file_h.read(chunk)
			file_r.write(temp)
			if self._threads_shutdown.is_set():
				break
			transfered += chunk
		GLib.idle_add(self._idle_update_status, transfered, size)
		file_h.close()
		file_r.close()
		ftp.close()
		GLib.idle_add(self._idle_refresh_directories)

	def _idle_refresh_directories(self):
		self.local.refresh()
		self.remote.refresh()

	def _idle_update_status(self, x, y):
		amount_done = min(int(float(x) / y * 100), 100)
		if amount_done == 100:
			self.logger._tv_model[self._id][3] = 'Complete'
		self.logger._tv_model[self._id][4] = amount_done
		return False

	### FIXME ###
	### TELL SPENCER ABOUT PROBLEM W UNUSED THREADS ###
	def _thread_routine(self, ssh):
		while not self._threads_shutdown.is_set():
			self._id, local_file, dest_file, direction = self.queue.get()
			if local_file is None:
				pass
			else:
				self._transfer(local_file, dest_file, ssh, direction)
				self.queue.task_done()

	def signal_window_destroy(self, _):
		self.window.set_sensitive(False)
		self._threads_shutdown.set()
		for _ in self._threads:
			self.queue.put([None, None, None, None])
		for thread in self._threads:
			thread.join()

	def upload(self, temp, temp1):
		selection = self.local.treeview.get_selection()
		model, treeiter = selection.get_selected()
		destination = self.remote.treeview.get_selection()
		dest_model, dest_treeiter = destination.get_selected()
		if treeiter is None:
			return
		local_file = model[treeiter][2]
		if dest_treeiter is None:
			dest_dir = self.remote.def_dir
		elif dest_model[dest_treeiter][5] != -1:
			return
		else:
			dest_dir = dest_model[dest_treeiter][2]
			if dest_model[dest_treeiter][3][3:] not in self.acceptable_perms:
				self.logger.log_transfer('Upload', local_file, dest_dir, 'Error', 0)
				return
		if model[treeiter][3][3:] not in self.acceptable_perms:
			self.logger.log_transfer('Upload', local_file, dest_dir, 'Error', 0)
			return
		unique = self.logger.log_transfer('Upload', local_file, dest_dir, 'Pending', 0)
		new_full_name = dest_dir + '/' + model[treeiter][0]
		self.queue_transfer(unique, local_file, new_full_name, 'U')

	def queue_transfer(self, _id, local_file, dest_file, direction):
		data_tuple = (_id, local_file, dest_file, direction)
		self.queue.put(data_tuple)

	def download(self, temp, temp1):
		selection = self.remote.treeview.get_selection()
		model, treeiter = selection.get_selected()
		destination = self.local.treeview.get_selection()
		dest_model, dest_treeiter = destination.get_selected()
		if treeiter is None:
			return
		local_file = model[treeiter][2]
		if dest_treeiter is None:
			dest_dir = os.path.abspath(os.sep)
		elif dest_model[dest_treeiter][5] != -1:
			return
		else:
			dest_dir = dest_model[dest_treeiter][2]
			if dest_model[dest_treeiter][3][3:] not in self.acceptable_perms:
				self.logger.log_transfer('Download', local_file, dest_dir, 'Error', 0)
				return
		if model[treeiter][3][3:] not in self.acceptable_perms:
				self.logger.log_transfer('Download', local_file, dest_dir, 'Error', 0)
				return
		unique = self.logger.log_transfer('Download', local_file, dest_dir, 'Pending', 0)
		new_full_name = dest_dir + '/' + model[treeiter][0]
		self.queue_transfer(unique, local_file, new_full_name, 'D')

