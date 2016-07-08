import os
import sys
import time
import stat

import king_phisher.client.plugins as plugins
import king_phisher.client.application as application
from king_phisher.client.widget import managers
from king_phisher.client import gui_utilities


from gi.repository import Gtk
from gi.repository import Gdk
from gi.repository import GObject
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
		self.window.resize(600,500)
		logger = Logger(self.builder)
		local = LocalDirectory(self.builder, logger)
		self.window.show_all()

class Logger(object):

	def __init__(self, builder, *args, **kwargs):
		self.builder = builder
		self.scroll = self.builder.get_object('scrolledwindow2')
		self.treeview_transfer = self.builder.get_object('SFTPClientGUI.treeview_transfer')
		self.progress_bar = self.builder.get_object('SFTPClientGUI.progressbar')
		self.label_file = self.builder.get_object('SFTPClientGUI.label')
		col = Gtk.TreeViewColumn()
		colText = Gtk.CellRendererText()
		colText.size = 5
		col.pack_start(colText, True)
		col.add_attribute(colText, "text", 0)
		self.treeview_transfer.append_column(col)
		self._tvmodel = Gtk.ListStore(str)
		self.treeview_transfer.connect('size-allocate', self._treeview_changed)
		self.treeview_transfer.set_model(self._tvmodel)

	def _treeview_changed(self, widget, event, data=None):
		adj = self.scroll.get_vadjustment()
		adj.set_value(0)

	def log_hidden(self, hidden):
		if hidden:
			string = 'Not Showing Hidden Files'
		else:
			string = 'Showing Hidden Files'
		self._tvmodel.prepend((string,))

	def log_transfer(self, path, size):
		metadata = os.stat(path)
		isFolder = stat.S_ISDIR(metadata.st_mode)
		if isFolder:
			string = 'Uploading ' + path + ' all its children...'
			self._tvmodel.prepend((string,))
			for _file in [x[0] for x in os.walk(path)]:
				string = 'Uploading ' + _file
				self._tvmodel.prepend((string,))
		else:
			string = 'Uploading ' + path
			self._tvmodel.prepend((string,))



class LocalDirectory(object):

	def __init__(self, builder, logger, *args, **kwargs):
		self.logger = logger
		self.builder = builder
		self.treeview_local = self.builder.get_object('SFTPClientGUI.treeview_local')
		tvm = managers.TreeViewManager(
			self.treeview_local,
			cb_refresh=self.load_dirs
		)
		col = Gtk.TreeViewColumn("File")
		colText = Gtk.CellRendererText()
		colImg = Gtk.CellRendererPixbuf()
		col.pack_start(colImg, False)
		col.pack_start(colText, True)
		col.add_attribute(colText, "text", 0)
		col.add_attribute(colImg, "pixbuf", 1)
		col.set_sort_column_id(0)
		col_size = Gtk.TreeViewColumn("Size")
		col_size.pack_start(colText, True)
		col_size.add_attribute(colText, "text", 3)
		col_size.set_sort_column_id(4)
		col_date = Gtk.TreeViewColumn("Date Modified")
		col_date.pack_start(colText, True)
		col_date.add_attribute(colText, "text", 5)
		col_date.set_sort_column_id(5)
		self.treeview_local.append_column(col)
		self.treeview_local.append_column(col_size)
		self.treeview_local.append_column(col_date)

		self.treeview_local.connect('row-expanded', self.expand_row)
		self.treeview_local.connect('row-collapsed', self.collapse_row)
		self.treeview_local.get_selection().set_mode(Gtk.SelectionMode.MULTIPLE)
		self._tvmodel = Gtk.TreeStore(str, Pixbuf, str, str, int, str)

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
		for item in os.listdir(path):
			if self.local_hidden and item.startswith('.'):
				continue
			name = item
			fullname = os.path.join(path, name)
			metadata = os.stat(fullname)
			date_modified = '   ' + time.strftime("%y-%m-%d %H:%M:%S", time.localtime(os.path.getmtime(fullname)))
			isFolder = stat.S_ISDIR(metadata.st_mode)
			if isFolder:
				icon = Gtk.IconTheme.get_default().load_icon('folder', 12.5, 0)
				current = self._tvmodel.append(parent, (name, icon, fullname, None, -1, date_modified))
			else:
				file_size = os.path.getsize(fullname)
				hr_file_size = '   ' + boltons.strutils.bytes2human(file_size)
				icon = Gtk.IconTheme.get_default().load_icon('empty', 12.5, 0)
				current = self._tvmodel.append(parent, (name, icon, fullname, hr_file_size, file_size,  date_modified))
			if isFolder:
				self._tvmodel.append(current, [None, None, None, None, None, None])
			counter +=1
		if counter < 1: 
			self._tvmodel.append(parent, [None, None, None, None, None, None])

	def expand_row(self, _, treeiter, treepath):
		try:
			newPath = self._tvmodel[treeiter][2]
			os.listdir(newPath)
			self.load_dirs(newPath, treeiter)
			self._tvmodel.remove(self._tvmodel.iter_children(treeiter))
		except (OSError, OverflowError) as ex:
			ex = type(ex).__name__
			dialog = self.builder.get_object('SFTPClientGUI.dialog_error')
			button = self.builder.get_object('button_exit')
			label = self.builder.get_object('label_error')
			if ex == 'OSError':
				label.set_text("Sorry, you have invalid \n permissions to view \n the selected materials")
			else: 
				label.set_text("Sorry, the folder you are \n trying to access is too large to be supported, \n this probably means you shouldn't be \n going here anyway...")
			button.connect('clicked', lambda x: dialog.hide())
			dialog.connect('delete-event', lambda x, y: x.hide() or True)
			dialog.show_all()
			self.collapse_row(_, treeiter, treepath)
			
			

	def collapse_row(self, _, treeiter, treepath):
		current = self._tvmodel.iter_children(treeiter)
		while current:
			self._tvmodel.remove(current)
			current = self._tvmodel.iter_children(treeiter)
		self._tvmodel.append(treeiter, [None, None, None, None, None, None])

	def upload(self, _):
		selection = self.treeview_local.get_selection()
		model, treeiter = selection.get_selected_rows()
		for _iter in treeiter:
			self.logger.log_transfer(model[_iter][2], model[_iter][4])

	def hidden_files(self, _):
		self.local_hidden = not self.local_hidden
		model = self._tvmodel
		exp_lines = []
		model.foreach(lambda model, path, iter: exp_lines.append(path) if self.treeview_local.row_expanded(path) else 0)
		self.treeview_local.collapse_all()
		for path in exp_lines:
			self.treeview_local.expand_row(path, False)
		self.logger.log_hidden(self.local_hidden)
