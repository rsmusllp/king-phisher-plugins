import os
import sys
import time
import stat
import shutil

import king_phisher.client.plugins as plugins

from gi.repository import Gtk
from gi.repository.GdkPixbuf import Pixbuf

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
		module = sys.modules['king_phisher.client.application']
		self.temp = module.KingPhisherClientApplication.do_sftp_client_start
		module.KingPhisherClientApplication.do_sftp_client_start = self.new_SFTP_signal
		sys.modules['king_phisher.client.application'] = module
		return True

	def _cleanup(self):
		module = sys.modules['king_phisher.client.application']
		module.KingPhisherClientApplication.do_sftp_client_start = self.temp
		sys.modules['king_phisher.client.application'] = module

	def new_SFTP_signal(self):
		if not self.application._ssh_forwarder:
			config = self.application.config
			server = config['server']
			server = server.split(':')
			username = config['server_username']
			password = config['server_password']
			self.application._create_ssh_forwarder(server, username, password)
		connection = self.application._ssh_forwarder
		ssh = connection.client
		ftp = ssh.open_sftp()

		target_file = os.path.splitext(__file__)[0]
		builder = Gtk.Builder()
		builder.add_from_file(target_file + '.ui')
		self.window = builder.get_object('SFTPClientGUI.window')
		manager = FileManager(builder, self.application, ftp)  #pylint: disable=unused-variable
		self.window.show_all()

class Logger(object):
	def __init__(self, builder, *args, **kwargs):
		self.builder = builder
		self.scroll = self.builder.get_object('scrolledwindow2')
		self.treeview_transfer = self.builder.get_object('SFTPClientGUI.treeview_transfer')
		self.progress_bar = self.builder.get_object('SFTPClientGUI.progressbar')
		self.label_file = self.builder.get_object('SFTPClientGUI.label')
		col = Gtk.TreeViewColumn('Transfer')
		colText = Gtk.CellRendererText()
		col.pack_start(colText, True)
		col.add_attribute(colText, "text", 0)
		self.treeview_transfer.append_column(col)
		self._tvmodel = Gtk.ListStore(str)
		self.treeview_transfer.connect('size-allocate', self._treeview_changed)
		self.treeview_transfer.set_model(self._tvmodel)
		self.treeview_transfer.connect('button_press_event', self._signal_treeview_button_pressed)

		self.popup_menu = Gtk.Menu.new()
		menu_item = Gtk.MenuItem.new_with_label('Clear')
		menu_item.connect('activate', self.clear_log)
		self.popup_menu.append(menu_item)
		self.popup_menu.show_all()

	def _signal_treeview_button_pressed(self, _, event):
		if event.button == 3:
			self.popup_menu.popup(None, None, None, None, event.button, Gtk.get_current_event_time())
			return True
		return

	def log_generic(self, string):
		self._tvmodel.prepend((string,))

	def clear_log(self, _):
		self._tvmodel.clear()

	def _treeview_changed(self, widget, event, data=None):
		adj = self.scroll.get_vadjustment()
		adj.set_value(0)

	def log_transfer_upload(self, path, size, isFolder, error=False):
		if error:
			string = 'Error uploading ' + path
			self._tvmodel.prepend((string,))
		elif isFolder:
			string = 'Uploading folder ' + path + ' and all its children...'
			self._tvmodel.prepend((string,))
		else:
			string = 'Uploading ' + path
			self._tvmodel.prepend((string,))

class DirectoryBase(object):
	def __init__(self, treeview, logger):
		col = Gtk.TreeViewColumn("Files")
		self.logger = logger
		self.treeview_local = treeview
		colText = Gtk.CellRendererText()
		colImg = Gtk.CellRendererPixbuf()
		col.pack_start(colImg, False)
		col.pack_start(colText, True)
		col.add_attribute(colText, "text", 0)
		col.add_attribute(colImg, "pixbuf", 1)
		col.set_sort_column_id(0)
		col_perm = Gtk.TreeViewColumn("Permissions")
		col_perm.pack_start(colText, True)
		col_perm.add_attribute(colText, "text", 3)
		col_size = Gtk.TreeViewColumn("Size")
		col_size.pack_start(colText, True)
		col_size.add_attribute(colText, "text", 4)
		col_size.set_sort_column_id(5)
		col_date = Gtk.TreeViewColumn("Date Modified")
		col_date.pack_start(colText, True)
		col_date.add_attribute(colText, "text", 6)
		col_date.set_sort_column_id(6)
		self.treeview_local.append_column(col)
		self.treeview_local.append_column(col_perm)
		self.treeview_local.append_column(col_size)
		self.treeview_local.append_column(col_date)

		self.treeview_local.connect('row-expanded', self.expand_row)
		self.treeview_local.connect('row-collapsed', self.collapse_row)
		self._tvmodel = Gtk.TreeStore(str, Pixbuf, str, str, str, int, str)

		self.local_hidden = True
		self.treeview_local.connect('button_press_event', self._signal_treeview_button_pressed)

		self.popup_menu = Gtk.Menu.new()
		menu_item = Gtk.CheckMenuItem.new_with_label('Show Hidden Files')
		menu_item.connect('toggled', self.hidden_files)
		self.hidden_files = menu_item
		self.popup_menu.append(menu_item)

		menu_item = Gtk.MenuItem.new_with_label('Delete')
		menu_item.connect('activate', self.delete_prompt)
		self.popup_menu.append(menu_item)
		self.popup_menu.show_all()

	def _signal_treeview_button_pressed(self, _, event):
		if event.button == 3:
			self.popup_menu.popup(None, None, None, None, event.button, Gtk.get_current_event_time())
			return True
		return

	def expand_row(self, _, treeiter, treepath):
		newPath = self._tvmodel[treeiter][2]  # pylint: disable=unsubscriptable-object
		self.load_dirs(newPath, treeiter)
		self._tvmodel.remove(self._tvmodel.iter_children(treeiter))

	def collapse_row(self, _, treeiter, treepath):
		current = self._tvmodel.iter_children(treeiter)
		while current:
			self._tvmodel.remove(current)
			current = self._tvmodel.iter_children(treeiter)
		self._tvmodel.append(treeiter, [None, None, None, None, None, None, None])

	def hidden_files(self, _):  # pylint: disable=method-hidden
		self.local_hidden = not self.local_hidden
		self.refresh()

	def refresh(self):
		model = self._tvmodel
		exp_lines = []
		model.foreach(lambda model, path, iter: exp_lines.append(path) if self.treeview_local.row_expanded(path) else 0)
		self.treeview_local.collapse_all()
		for path in exp_lines:
			self.treeview_local.expand_row(path, False)

	def delete_prompt(self, _):
		selection = self.treeview_local.get_selection()
		model, treeiter = selection.get_selected()
		dialog = Gtk.Dialog('Warning')
		label = 'Are you sure\n you want to delete this {0}?\n'.format('directory' if model[treeiter][5] == -1 else 'file')
		label = Gtk.Label(label)
		label.set_justify(Gtk.Justification.CENTER)
		dialog.vbox.pack_start(label, True, True, 0)
		label.show()
		dialog.add_button(Gtk.STOCK_CANCEL, Gtk.ResponseType.REJECT)
		dialog.add_button(Gtk.STOCK_OK, Gtk.ResponseType.ACCEPT)
		response_id = dialog.run()
		dialog.destroy()
		if response_id == -3:
			self.delete(model, treeiter)

class LocalDirectory(DirectoryBase):
	def __init__(self, treeview, logger, upload_button, *args, **kwargs):
		super(LocalDirectory, self).__init__(treeview, logger)
		self.upload_button = upload_button
		self.load_dirs(os.path.abspath(os.sep))
		self.treeview_local.set_model(self._tvmodel)

	def load_dirs(self, path, parent=None):
		counter = 0
		for name in os.listdir(path):
			if self.local_hidden and name.startswith('.'):
				continue
			fullname = os.path.join(path, name)
			r_permissions = os.access(fullname, os.R_OK)
			w_permissions = os.access(fullname, os.W_OK)
			x_permissions = os.access(fullname, os.X_OK)
			perm = '   '
			perm = perm + 'r' if r_permissions else perm + '-'
			perm = perm + 'w' if w_permissions else perm + '-'
			perm = perm + 'x' if x_permissions else perm + '-'
			date_modified = '   ' + time.strftime("%y-%m-%d %H:%M:%S", time.localtime(os.path.getmtime(fullname)))
			isFolder = stat.S_ISDIR(os.stat(fullname).st_mode)
			if isFolder:
				icon = Gtk.IconTheme.get_default().load_icon('folder', 20, 0)
				if not (r_permissions and x_permissions):
					icon = Gtk.IconTheme.get_default().load_icon('emblem-unreadable', 13, 0)
				current = self._tvmodel.append(parent, (name, icon, fullname, perm, None, -1, date_modified))
			else:
				file_size = os.path.getsize(fullname)
				hr_file_size = '   ' + boltons.strutils.bytes2human(file_size)
				if not (r_permissions and x_permissions):
					icon = Gtk.IconTheme.get_default().load_icon('emblem-unreadable', 13, 0)
				icon = Gtk.IconTheme.get_default().load_icon('empty', 12.5, 0)
				current = self._tvmodel.append(parent, (name, icon, fullname, perm, hr_file_size, file_size, date_modified))
			if isFolder and (r_permissions and x_permissions):
				self._tvmodel.append(current, [None, None, None, None, None, None, None])
			counter += 1
		if counter < 1:
			self._tvmodel.append(parent, [None, None, None, None, None, None, None])

	def delete(self, model, treeiter):
		try:
			if model[treeiter][5] == -1:
				shutil.rmtree(model[treeiter][2])
			else:
				os.remove(model[treeiter][2])
			self.logger.log_generic('Successfully deleted ' + model[treeiter][2])
			self.refresh()
		except OSError:
			self.logger.log_generic("Permissions Error Deleting File")

class RemoteDirectory(DirectoryBase):
	def __init__(self, treeview, logger, download_button, application, ftp, *args, **kwargs):
		super(RemoteDirectory, self).__init__(treeview, logger, *args, **kwargs)
		self.ftp = ftp
		self.download_button = download_button
		self.application = application
		self.def_dir = self.application.config['server_config']['server.web_root']
		self.load_dirs(self.def_dir)
		self.treeview_local.set_model(self._tvmodel)

	def load_dirs(self, path, parent=None):
		self.ftp.chdir(path)
		counter = 0
		for name in self.ftp.listdir(path):
			if self.local_hidden and name.startswith('.'):
				continue
			fullname = path + '/' + name
			lstatout = self.ftp.lstat(fullname)
			perm = '   '
			_file = self.ftp.file(fullname)
			perm += 'r' if _file.readable() else '-'
			perm += 'w' if _file.writable() else '-'
			perm += '-'
			_file.close()
			date_modified = '   ' + time.strftime("%y-%m-%d %H:%M:%S", time.localtime(lstatout.st_mtime))
			isFolder = stat.S_ISDIR(lstatout.st_mode)
			if isFolder:
				icon = Gtk.IconTheme.get_default().load_icon('folder', 20, 0)
				current = self._tvmodel.append(parent, (name, icon, fullname, perm, None, -1, date_modified))
			else:
				file_size = lstatout.st_size
				hr_file_size = '   ' + boltons.strutils.bytes2human(file_size)
				icon = Gtk.IconTheme.get_default().load_icon('empty', 12.5, 0)
				current = self._tvmodel.append(parent, (name, icon, fullname, perm, hr_file_size, file_size, date_modified))
			if isFolder:
				self._tvmodel.append(current, [None, None, None, None, None, None, None])
			counter += 1
		if counter < 1:
			self._tvmodel.append(parent, [None, None, None, None, None, None, None])

	def delete(self, model, treeiter):
		try:
			self.ftp.remove(model[treeiter][2])
			self.logger.log_generic('Successfully deleted ' + model[treeiter][2])
			self.refresh()
		except IOError:
			self.logger.log_generic("Permissions Error Deleting File")

class FileManager(object):
	def __init__(self, builder, application, ftp, *args, **kwargs):
		self.builder = builder
		self.application = application
		upload_button = self.builder.get_object('button_upload')
		download_button = self.builder.get_object('button_download')
		self.logger = Logger(self.builder)
		self.local = LocalDirectory(self.builder.get_object('SFTPClientGUI.treeview_local'), self.logger, upload_button, ftp)  # pylint: disable=unused-variable
		self.remote = RemoteDirectory(self.builder.get_object('SFTPClientGUI.treeview_remote'), self.logger, download_button, self.application, ftp)  # pylint: disable=unused-variable
		self.local.upload_button.connect('button-press-event', self.upload)
		self.remote.download_button.connect('button-press-event', self.download)
		self.acceptable_perms = ('r-x', 'r--', 'rwx', 'rw-')

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
			dest_dir = os.path.abspath(os.sep)
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

