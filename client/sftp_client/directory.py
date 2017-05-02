import collections
import contextlib
import datetime
import errno
import logging
import os
import posixpath
import shutil
import stat
import threading

import boltons.strutils
import boltons.timeutils

from . import sftp_utilities
from . import editor

from king_phisher import its
from king_phisher import utilities
from king_phisher.client import gui_utilities

from gi.repository import Gtk
from gi.repository import Gdk
from gi.repository import GdkPixbuf

if its.on_windows:
	import win32api
	import win32con

GTYPE_LONG = sftp_utilities.GTYPE_LONG

PARENT_DIRECTORY = '..'
CURRENT_DIRECTORY = '.'
logger = logging.getLogger('KingPhisher.Plugins.SFTPClient.directory')
ObjectLock = collections.namedtuple('ObjectLock', ('object', 'lock'))
DirectoryContents = collections.namedtuple('DirectoryContents', ('dirpath', 'dirnames', 'filenames'))

class DirectoryBase(object):
	"""
	Base directory object that is used by both the remote and local directory to
	get and render directory data.
	"""
	def __init__(self, application, config, wd_history):
		self.application = application
		self.config = config
		self.treeview = sftp_utilities.get_object('SFTPClient.notebook.page_stfp.' + self.treeview_name)
		self.notebook = sftp_utilities.get_object('SFTPClient.notebook')
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
		self.treeview.append_column(sftp_utilities.get_treeview_column('Permissions', col_text, 3, m_col_sort=3, resizable=True))
		self.treeview.append_column(sftp_utilities.get_treeview_column('Size', col_text, 4, m_col_sort=5, resizable=True))
		self.treeview.append_column(sftp_utilities.get_treeview_column('Date Modified', col_text, 6, m_col_sort=6, resizable=True))

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
		self.wdcb_dropdown = sftp_utilities.get_object(self.working_directory_combobox_name)
		self.wdcb_dropdown.set_model(self._wdcb_model)
		self.wdcb_dropdown.set_entry_text_column(0)
		self.wdcb_dropdown.connect('changed', sftp_utilities.DelayedChangedSignal(self.signal_combo_changed))

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

		# if empty placeholder just delete
		if not self._tv_model[treeiter][2]:
			self._tv_model.remove(treeiter)
			return

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

		self.menu_item_edit = Gtk.MenuItem.new_with_label('Edit')
		self.popup_menu.append(self.menu_item_edit)

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
		try:
			self._chdir(new_dir)
		except OSError:
			logger.warning("user does not have permissions to read {}".format(new_dir))
			gui_utilities.show_dialog_error(
				'Plugin Error',
				self.application.get_active_window(),
				"You do not have permissions to access {}.".format(new_dir)
			)
			return

		self._tv_model.clear()
		try:
			self.load_dirs(new_dir)
		except OSError:
			logger.warning("user does not have permissions to read {}".format(new_dir))
			self.load_dirs(self.cwd)
			gui_utilities.show_dialog_error(
				'Plugin Error',
				self.application.get_active_window(),
				"You do not have permissions to access {}.".format(new_dir)
			)
			return

		self.cwd = new_dir
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
		if not self.get_is_folder(model[treeiter][2]):
			logger.warning('cannot set a file as an active working directory')
			gui_utilities.show_dialog_error(
				'Plugin Error',
				self.application.get_active_window(),
				'Cannot set a file the working directory.'
			)
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
		model, treeiter = selection.get_selected()
		if treeiter:
			if not self.get_is_folder(model[treeiter][2]):
				logger.warning('cannot create a directory under a file')
				gui_utilities.show_dialog_error(
					'Plugin Error',
					self.application.get_active_window(),
					'Cannot create a directory under a file.'
				)
				return
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
		# if empty placeholder was not named assume user bailed creation
		if not text or text == ' ' and not self._tv_model[treeiter][2]:
			self._tv_model.remove(treeiter)
			return
		if not text or text == self._tv_model[treeiter][0]:
			return
		if stat.S_ISDIR(self.path_mode(new_path)):
			gui_utilities.show_dialog_error('Unable to make directory', self.application.get_active_window(), "Directory: {0} already exists".format(new_path))
			return
		if self._tv_model[treeiter][2] is not None:
			try:
				self._rename_file(treeiter, new_path)
			except (OSError, IOError):
				gui_utilities.show_dialog_error('Plugin Error', self.application.get_active_window(), 'Error renaming the file.')
		else:
			self._tv_model.remove(treeiter)
			try:
				self.make_dir(new_path)
			except (OSError, IOError):
				gui_utilities.show_dialog_error('Plugin Error', self.application.get_active_window(), 'Error creating the directory.')
		self.refresh()

	def signal_menu_activate_delete_prompt(self, _):
		self._delete_selection()

class LocalDirectory(DirectoryBase):
	"""
	Local Directory object that defines private methods for rendering local data
	using the os module.
	"""
	location = 'local'
	root_directory = os.path.abspath(os.sep)
	transfer_direction = 'upload'
	treeview_name = 'treeview_local'
	working_directory_combobox_name = 'SFTPClient.notebook.page_stfp.comboboxtext_local_working_directory'
	def __init__(self, application, config):
		self.stat = os.stat
		self._chdir = os.chdir
		self.path_mod = os.path
		self.default_directory = self.path_mod.expanduser('~')
		local_directories = config['directories'].get('local', {})
		wd_history = local_directories.get('history', [])
		super(LocalDirectory, self).__init__(application, config, wd_history)
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

	def read_file(self, local_file_path):
		"""
		Used to fetch the contents of target file
		:param str local_file_path: the absolute path to target file
		:return: the utf-8 contents of the file
		:rtype: str
		"""
		if not (local_file_path and os.path.isfile(local_file_path) and os.access(local_file_path, os.R_OK)):
			logger.warning('cannot write to local file, or file not found')
			raise ValueError("Cannot read file {}".format(local_file_path))
		with open(local_file_path, 'r') as file_:
			file_contents = file_.read()
		return file_contents

	def save_file(self, local_file_path, buffer_contents):
		"""
		Saves a string to a file

		:param str local_file_path: The absolute path to target file.
		:param str buffer_contents: The data to place in file.
		"""
		if not (local_file_path and os.path.isfile(local_file_path) and os.access(local_file_path, os.W_OK)):
			logger.warning('cannot write to local file, or file not found')
			raise IOError("Cannot write to local file, or file not found")
		file_ = open(local_file_path, 'w')
		file_.write(buffer_contents)
		file_.close()
		logger.info('saved edited to file {}'.format(local_file_path))

	@sftp_utilities.handle_permission_denied
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
		logger.info("deleting {0}: {1}".format(('directory' if self._tv_model[treeiter][5] == -1 else 'file'), row[2]))
		self._tv_model.remove(treeiter)

	@sftp_utilities.handle_permission_denied
	def remove_by_folder_name(self, name):
		"""
		Removes a folder given its absolute path.

		:param name: The path of the folder to be removed.
		"""
		shutil.rmtree(name)

	@sftp_utilities.handle_permission_denied
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
	location = 'remote'
	root_directory = posixpath.abspath(posixpath.sep)
	transfer_direction = 'download'
	treeview_name = 'treeview_remote'
	working_directory_combobox_name = 'SFTPClient.notebook.page_stfp.comboboxtext_remote_working_directory'
	def __init__(self, application, config, ssh):
		self.ssh = ssh
		self.path_mod = posixpath
		wd_history = config['directories'].get('remote', {})
		wd_history = wd_history.get(application.config['server'].split(':', 1)[0], [])
		self._thread_local_ftp = {}
		super(RemoteDirectory, self).__init__(application, config, wd_history)

		self.default_directory = application.config['server_config']['server.web_root']
		try:
			self.change_cwd(self.default_directory)
		except (IOError, OSError):
			logger.info("failed to set remote directory to the web root: " + application.config['server_config']['server.web_root'])
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

	@sftp_utilities.handle_permission_denied
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

	@sftp_utilities.handle_permission_denied
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

	@sftp_utilities.handle_permission_denied
	def remove_by_file_name(self, name):
		"""
		Removes a file given its absolute path.

		:param name: The path of the file to be removed.
		"""
		with self.ftp_handle() as ftp:
			ftp.remove(name)

	def read_file(self, file_path):
		"""
		Reads the contents of a file and returns as bytes

		:param str file_path: The path to the file to open and read. 
		:return: The contents of the file
		:rtype: bytes
		"""
		with self.ftp_handle() as ftp:
			with ftp.file(file_path, 'r') as file_:
				file_contents = file_.read()
		return file_contents

	def save_file(self, file_path, file_contents):
		"""
		Saves a raw string to the remote file path
		
		:param str file_path: Remote file path
		:param str file_contents: the contents to place in the file
		"""
		with self.ftp_handle() as ftp:
			file_ = ftp.file(file_path, 'w')
			file_.write(file_contents)
			file_.close()

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
