import os
import sys
import time
import stat

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
		target_file = os.path.splitext(__file__)[0]
		self.builder = Gtk.Builder()
		self.builder.add_from_file(target_file + '.ui')
		self.window = self.builder.get_object('SFTPClientGUI.window')
		logger = Logger(self.builder)
		local = LocalDirectory(self.builder.get_object('SFTPClientGUI.treeview_local'), logger)  # pylint: disable=unused-variable
		remote = RemoteDirectory(self.builder.get_object('SFTPClientGUI.treeview_remote'), logger, self.application)  # pylint: disable=unused-variable
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
		colText.size = 5
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

	def clear_log(self, _):
		self._tvmodel.clear()

	def _treeview_changed(self, widget, event, data=None):
		adj = self.scroll.get_vadjustment()
		adj.set_value(0)

	def log_hidden(self, hidden):
		if hidden:
			string = 'Not Showing Hidden Files'
		else:
			string = 'Showing Hidden Files'
		self._tvmodel.prepend((string,))

	def log_transfer(self, path, size, isFolder, error=False):
		if error:
			string = 'Error uploading ' + path
			self._tvmodel.prepend((string,))
		elif isFolder:
			string = 'Uploading folder ' + path + ' and all its children...'
			self._tvmodel.prepend((string,))

		else:
			string = 'Uploading ' + path
			self._tvmodel.prepend((string,))



class LocalDirectory(object):

	def __init__(self, treeview, logger, *args, **kwargs):
		self.logger = logger
		self.treeview_local = treeview
		col = Gtk.TreeViewColumn("Local Filesystem")
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
		self.treeview_local.get_selection().set_mode(Gtk.SelectionMode.MULTIPLE)
		self._tvmodel = Gtk.TreeStore(str, Pixbuf, str, str, str, int, str)

		self.local_hidden = True
		self.load_dirs(os.path.abspath(os.sep))
		self.treeview_local.set_model(self._tvmodel)
		self.treeview_local.connect('button_press_event', self._signal_treeview_button_pressed)
		self.popup_menu = Gtk.Menu.new()
		menu_item = Gtk.CheckMenuItem.new_with_label('Show Hidden Files')
		menu_item.connect('toggled', self.hidden_files)
		self.hidden_files = menu_item
		self.popup_menu.append(menu_item)

		menu_item = Gtk.MenuItem.new_with_label('Upload Selected')
		menu_item.connect('activate', self.upload)
		self.popup_menu.append(menu_item)

		self.popup_menu.show_all()


	def _signal_treeview_button_pressed(self, _, event):
		if event.button == 3:
			self.popup_menu.popup(None, None, None, None, event.button, Gtk.get_current_event_time())
			return True
		return

	def load_dirs(self, path, parent=None):
		counter = 0
		for name in os.listdir(path):
			if self.local_hidden and name.startswith('.'):
				continue
			fullname = os.path.join(path, name)
			metadata = os.stat(fullname)
			r_permissions = os.access(fullname, os.R_OK)
			w_permissions = os.access(fullname, os.W_OK)
			x_permissions = os.access(fullname, os.X_OK)
			perm = '   '
			perm = perm + 'r' if r_permissions else perm + '-'
			perm = perm + 'w' if w_permissions else perm + '-'
			perm = perm + 'x' if x_permissions else perm + '-'
			date_modified = '   ' + time.strftime("%y-%m-%d %H:%M:%S", time.localtime(os.path.getmtime(fullname)))
			isFolder = stat.S_ISDIR(metadata.st_mode)
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

	def upload(self, _):
		selection = self.treeview_local.get_selection()
		model, treeiter = selection.get_selected_rows()
		for _iter in treeiter:
			path = model[_iter][2]
			metadata = os.stat(path)
			isFolder = stat.S_ISDIR(metadata.st_mode)
			if not os.access(path, os.R_OK):
				self.logger.log_transfer(path, None, None, True)
			elif isFolder:
				for _dir in [x[0] for x in os.walk(path)]:
					temp = _dir.split('/')
					temp_bool = False
					if self.local_hidden:
						for x in temp:
							if x.startswith('.'):
								temp_bool = True
					if temp_bool:
						continue
					self.logger.log_transfer(_dir, None, True)
					for _file in os.listdir(_dir):
						if _file.startswith('.') and self.local_hidden:
							continue
						_file = _dir + '/' + _file
						try:
							metadata = os.stat(_file)
						except OSError:
							self.logger.log_transfer(_file, None, None, True)
							continue
						isFolder = stat.S_ISDIR(metadata.st_mode)
						if isFolder:
							continue
						file_size = os.path.getsize(_file)
						self.logger.log_transfer(_file, file_size, False)

			else:
				if model[_iter][2].startswith('.') and self.local_hidden:
					continue
				self.logger.log_transfer(model[_iter][2], model[_iter][4], isFolder)

	def hidden_files(self, _):  # pylint: disable=method-hidden
		self.local_hidden = not self.local_hidden
		model = self._tvmodel
		exp_lines = []
		model.foreach(lambda model, path, iter: exp_lines.append(path) if self.treeview_local.row_expanded(path) else 0)
		self.treeview_local.collapse_all()
		for path in exp_lines:
			self.treeview_local.expand_row(path, False)
		self.logger.log_hidden(self.local_hidden)

class RemoteDirectory(LocalDirectory):
	def __init__(self, treeview, logger, application, *args, **kwargs):  #pylint: disable=super-init-not-called
		self.logger = logger
		self.treeview_local = treeview
		col = Gtk.TreeViewColumn("Remote Filesystem")
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
		self.treeview_local.get_selection().set_mode(Gtk.SelectionMode.MULTIPLE)
		self._tvmodel = Gtk.TreeStore(str, Pixbuf, str, str, str, int, str)

		self.application = application
		if not self.application._ssh_forwarder:
			config = self.application.config
			server = config['server']
			server = server.split(':')
			username = config['server_username']
			password = config['server_password']
			self.application._create_ssh_forwarder(server, username, password)
		connection = self.application._ssh_forwarder
		ssh = connection.client
		self.ftp = ssh.open_sftp()
		self.local_hidden = True
		self.load_dirs('/var/www/')
		self.treeview_local.set_model(self._tvmodel)
		self.treeview_local.connect('button_press_event', self._signal_treeview_button_pressed)
		self.popup_menu = Gtk.Menu.new()
		menu_item = Gtk.CheckMenuItem.new_with_label('Show Hidden Files')
		menu_item.connect('toggled', self.hidden_files)
		self.hidden_files = menu_item
		self.popup_menu.append(menu_item)

		menu_item = Gtk.MenuItem.new_with_label('Download Selected')
		menu_item.connect('activate', self.upload)
		self.popup_menu.append(menu_item)

		self.popup_menu.show_all()

	def load_dirs(self, path, parent=None):
		self.ftp.chdir(path)
		counter = 0
		for item in self.ftp.listdir(path):
			if self.local_hidden and item.startswith('.'):
				continue
			name = item
			fullname = path + '/' + name
			lstatout = self.ftp.lstat(fullname)
			perm = '   ---'
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
