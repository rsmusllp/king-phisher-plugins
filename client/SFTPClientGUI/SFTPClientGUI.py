import os
import time
import stat
import shutil

import king_phisher.client.plugins as plugins

from gi.repository import Gtk
from gi.repository.GdkPixbuf import Pixbuf
from gi.repository import Gdk
from gi.repository import GObject

import boltons.strutils
import boltons.timeutils

class Plugin(plugins.ClientPlugin):
	authors = ['Josh Jacob']
	title = 'SFTP Client GUI'
	description = """
	How many foos could fu foo is fu fooed fu foos on foo.
	"""
	homepage = 'https://github.com/securestate/king-phisher'

	def initialize(self):
		self.sftp_window = None
		self.signal_connect('sftp-client-start', self.signal_sftp_start)
		return True

	def signal_sftp_start(self, _):
		GObject.signal_stop_emission_by_name(self.application, 'sftp-client-start')
		if self.sftp_window is None:
			connection = self.application._ssh_forwarder
			if connection is None:
				self.logger.warning('Invalid connection, use ip address instead of localhost')
				return
			ssh = connection.client
			ftp = ssh.open_sftp()
			target_file = os.path.splitext(__file__)[0] + '.ui'
			self.logger.debug('loading gtk builder file from: ' + target_file)
			manager = FileManager(target_file, self.application, ftp)  #pylint: disable=unused-variable
			self.sftp_window = manager.window
		self.sftp_window.show()
		self.sftp_window.get_focus()

class Logger(object):
	def __init__(self, builder, *args, **kwargs):
		self.builder = builder
		self.scroll = self.builder.get_object('logger_scroll')
		self.treeview_transfer = self.builder.get_object('SFTPClientGUI.treeview_transfer')
		self.progress_bar = self.builder.get_object('SFTPClientGUI.progressbar')
		self.label_file = self.builder.get_object('SFTPClientGUI.label')
		col = Gtk.TreeViewColumn('Transfer')
		col_text = Gtk.CellRendererText()
		col.pack_start(col_text, True)
		col.add_attribute(col_text, "text", 0)
		self.treeview_transfer.append_column(col)
		self._tvmodel = Gtk.ListStore(str)
		self.treeview_transfer.connect('size-allocate', self._treeview_changed)
		self.treeview_transfer.set_model(self._tvmodel)
		self.treeview_transfer.connect('button_press_event', self._signal_treeview_button_pressed)

		self.popup_menu = Gtk.Menu.new()
		menu_item = Gtk.MenuItem.new_with_label('Clear')
		menu_item.connect('activate', self.log_clear)
		self.popup_menu.append(menu_item)
		self.popup_menu.show_all()

	def _signal_treeview_button_pressed(self, _, event):
		if event.button == Gdk.BUTTON_SECONDARY:
			self.popup_menu.popup(None, None, None, None, event.button, Gtk.get_current_event_time())
			return True
		return

	def log_generic(self, string):
		self._tvmodel.prepend((string,))

	def log_clear(self, _):
		self._tvmodel.clear()

	def _treeview_changed(self, widget, event, data=None):
		adj = self.scroll.get_vadjustment()
		adj.set_value(0)

	def log_transfer_upload(self, path, size, is_folder, error=False):
		if error:
			string = 'Error uploading ' + path
		elif is_folder:
			string = 'Uploading folder ' + path + ' and all its children...'
		else:
			string = 'Uploading ' + path
		self._tvmodel.prepend((string,))

class DirectoryBase(object):
	def __init__(self, treeview, logger):
		col = Gtk.TreeViewColumn('Files')
		self.logger = logger
		self.treeview_local = treeview
		col_text = Gtk.CellRendererText()
		col_img = Gtk.CellRendererPixbuf()
		col.pack_start(col_img, False)
		col.pack_start(col_text, True)
		col.add_attribute(col_text, 'text', 0)
		col.add_attribute(col_img, 'pixbuf', 1)
		col.set_sort_column_id(0)
		col_perm = Gtk.TreeViewColumn('Permissions')
		col_perm.pack_start(col_text, True)
		col_perm.add_attribute(col_text, 'text', 3)
		col_size = Gtk.TreeViewColumn('Size')
		col_size.pack_start(col_text, True)
		col_size.add_attribute(col_text, 'text', 4)
		col_size.set_sort_column_id(5)
		col_date = Gtk.TreeViewColumn('Date Modified')
		col_date.pack_start(col_text, True)
		col_date.add_attribute(col_text, 'text', 6)
		col_date.set_sort_column_id(6)
		self.treeview_local.append_column(col)
		self.treeview_local.append_column(col_perm)
		self.treeview_local.append_column(col_size)
		self.treeview_local.append_column(col_date)

		self.treeview_local.connect('row-expanded', self.signal_expand_row)
		self.treeview_local.connect('row-collapsed', self.signal_collapse_row)
		self._tvmodel = Gtk.TreeStore(str, Pixbuf, str, str, str, int, str)

		self.local_hidden = True
		self._get_popup_menu()

	def _get_popup_menu(self):
		self.treeview_local.connect('button_press_event', self._signal_treeview_button_pressed)

		self.popup_menu = Gtk.Menu.new()
		menu_item = Gtk.CheckMenuItem.new_with_label('Show Hidden Files')
		menu_item.connect('toggled', self.signal_menu_toggled_hidden_files)
		self.signal_menu_toggled_hidden_files = menu_item
		self.popup_menu.append(menu_item)

		menu_item = Gtk.MenuItem.new_with_label('Delete')
		menu_item.connect('activate', self.signal_menu_activate_delete_prompt)
		self.popup_menu.append(menu_item)
		self.popup_menu.show_all()

	def _signal_treeview_button_pressed(self, _, event):
		if event.button == Gdk.BUTTON_SECONDARY:
			self.popup_menu.popup(None, None, None, None, event.button, Gtk.get_current_event_time())
			return True
		return

	def signal_expand_row(self, _, treeiter, treepath):
		new_path = self._tvmodel[treeiter][2]  # pylint: disable=unsubscriptable-object
		self.load_dirs(new_path, treeiter)
		self._tvmodel.remove(self._tvmodel.iter_children(treeiter))

	def signal_collapse_row(self, _, treeiter, treepath):
		current = self._tvmodel.iter_children(treeiter)
		while current:
			self._tvmodel.remove(current)
			current = self._tvmodel.iter_children(treeiter)
		self._tvmodel.append(treeiter, [None, None, None, None, None, None, None])

	def load_dirs(self, path, parent=None):
		counter = 0
		dir_list = self._yield_dir_list(path)
		for name in dir_list:
			if self.local_hidden and name.startswith('.'):
				continue
			fullname = path + '/' + name
			perm = self._check_perm(fullname)
			raw_time = self._get_raw_time(fullname)
			date_modified = '   ' + time.strftime('%y-%m-%d %H:%M:%S', time.localtime(raw_time))
			is_folder = self._get_is_folder(fullname)
			if is_folder:
				icon = Gtk.IconTheme.get_default().load_icon('folder', 20, 0)
				if perm[3] != 'r' and perm[5] != 'x':
					icon = Gtk.IconTheme.get_default().load_icon('emblem-unreadable', 13, 0)
				current = self._tvmodel.append(parent, (name, icon, fullname, perm, None, -1, date_modified))
			else:
				file_size = self._get_file_size(fullname)
				hr_file_size = '   ' + boltons.strutils.bytes2human(file_size)
				if perm[3] != 'r' and perm[5] != 'x':
					icon = Gtk.IconTheme.get_default().load_icon('emblem-unreadable', 13, 0)
				icon = Gtk.IconTheme.get_default().load_icon('empty', 12.5, 0)
				current = self._tvmodel.append(parent, (name, icon, fullname, perm, hr_file_size, file_size, date_modified))
			if is_folder and perm[3] == 'r' and perm[5] == 'x':
				self._tvmodel.append(current, [None, None, None, None, None, None, None])
			counter += 1
		if counter < 1:
			self._tvmodel.append(parent, [None, None, None, None, None, None, None])

	def signal_menu_toggled_hidden_files(self, _):  # pylint: disable=method-hidden
		self.local_hidden = not self.local_hidden
		self.refresh()

	def refresh(self):
		model = self._tvmodel
		exp_lines = []
		model.foreach(lambda model, path, iter: exp_lines.append(path) if self.treeview_local.row_expanded(path) else 0)
		self.treeview_local.collapse_all()
		for path in exp_lines:
			self.treeview_local.expand_row(path, False)

	def signal_menu_activate_delete_prompt(self, _):
		selection = self.treeview_local.get_selection()
		model, treeiter = selection.get_selected()
		dialog = Gtk.Dialog('Warning')
		label = "Are you sure\n you want to delete this {0}?\n".format('directory' if model[treeiter][5] == -1 else 'file')
		label = Gtk.Label(label)
		label.set_justify(Gtk.Justification.CENTER)
		dialog.vbox.pack_start(label, True, True, 0)
		label.show()
		dialog.add_button(Gtk.STOCK_CANCEL, Gtk.ResponseType.REJECT)
		dialog.add_button(Gtk.STOCK_OK, Gtk.ResponseType.ACCEPT)
		response_id = dialog.run()
		dialog.destroy()
		if response_id == Gtk.ResponseType.ACCEPT:
			self.delete(model, treeiter)

class LocalDirectory(DirectoryBase):
	treeview_name = 'treeview_local'
	def __init__(self, builder, logger, upload_button):
		_treeview = builder.get_object('SFTPClientGUI.' + self.treeview_name)
		super(LocalDirectory, self).__init__(_treeview, logger)
		self.upload_button = upload_button
		init_dir = os.getcwd()
		self.load_dirs(init_dir)
		self.treeview_local.set_model(self._tvmodel)

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
		names = []
		for name in os.listdir(path):
			names.append(name)
		return names

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
			self.logger.log_generic('Successfully deleted ' + model[treeiter][2])
			self.refresh()
		except OSError:
			self.logger.log_generic('Permissions Error Deleting File')

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
		self.treeview_local.set_model(self._tvmodel)

	def _check_perm(self, fullname):
		lstatout = self.ftp.lstat(fullname)
		mode = lstatout.st_mode
		perm = '   '
		_file = self.ftp.file(fullname)
		perm += 'r' if _file.readable() else '-'
		perm += 'w' if _file.writable() else '-'
		_file.close()
		perm += 'x' if bool(int(oct(mode)[2:]) & stat.S_IXOTH) else '-'
		return perm

	def _yield_dir_list(self, path):
		names = []
		for name in self.ftp.listdir(path):
			names.append(name)
		return names

	def _get_raw_time(self, fullname):
		lstatout = self.ftp.lstat(fullname)
		return lstatout.st_mtime

	def _get_is_folder(self, fullname):
		lstatout = self.ftp.lstat(fullname)
		mode = lstatout.st_mode
		return stat.S_ISDIR(mode)

	def _get_file_size(self, fullname):
		lstatout = self.ftp.lstat(fullname)
		return lstatout.st_size

	def delete(self, model, treeiter):
		try:
			self.ftp.remove(model[treeiter][2])
			self.logger.log_generic('Successfully deleted ' + model[treeiter][2])
			self.refresh()
		except IOError:
			self.logger.log_generic('Permissions Error Deleting File')

class FileManager(object):
	def __init__(self, target_file, application, ftp, *args, **kwargs):
		self.builder = Gtk.Builder()
		self.builder.add_from_file(target_file)
		self.window = self.builder.get_object('SFTPClientGUI.window')
		self.application = application
		upload_button = self.builder.get_object('button_upload')
		download_button = self.builder.get_object('button_download')
		self.logger = Logger(self.builder)
		self.local = LocalDirectory(self.builder, self.logger, upload_button)  # pylint: disable=unused-variable
		self.remote = RemoteDirectory(self.builder, self.logger, download_button, self.application, ftp)  # pylint: disable=unused-variable
		self.local.upload_button.connect('button-press-event', self.upload)
		self.remote.download_button.connect('button-press-event', self.download)
		self.acceptable_perms = ('r-x', 'r--', 'rwx', 'rw-')
		self.window.show_all()

	def upload(self, temp, temp1):
		selection = self.local.treeview_local.get_selection()
		model, treeiter = selection.get_selected()
		destination = self.remote.treeview_local.get_selection()
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
				self.logger.log_generic("Error uploading {0} to {1}".format(local_file, dest_dir))
				return
		if model[treeiter][3][3:] not in self.acceptable_perms:
			self.logger.log_generic("Error uploading {0} to {1}".format(local_file, dest_dir))
			return
		self.logger.log_generic("Uploading {0} to {1}".format(local_file, dest_dir))

	def download(self, temp, temp1):
		selection = self.remote.treeview_local.get_selection()
		model, treeiter = selection.get_selected()
		destination = self.local.treeview_local.get_selection()
		dest_model, dest_treeiter = destination.get_selected()
		if treeiter is None:
			return
		local_file = model[treeiter][2]
		if dest_treeiter is None:
			dest_dir = os.getcwd()
		elif dest_model[dest_treeiter][5] != -1:
			return
		else:
			dest_dir = dest_model[dest_treeiter][2]
			if dest_model[dest_treeiter][3][3:] not in self.acceptable_perms:
				self.logger.log_generic("Error downloading {0} to {1}".format(local_file, dest_dir))
				return
		if model[treeiter][3][3:] not in self.acceptable_perms:
			self.logger.log_generic("Error downloading {0} to {1}".format(local_file, dest_dir))
			return
		self.logger.log_generic("Downloading {0} to {1}".format(local_file, dest_dir))
