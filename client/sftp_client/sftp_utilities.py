import logging
import threading
import os

from king_phisher.client import gui_utilities

from gi.repository import Gtk
from gi.repository import GLib
from gi.repository import GObject

logger = logging.getLogger('KingPhisher.Plugins.SFTPClient')
GTYPE_LONG = GObject.type_from_name('glong')
gtk_builder_file = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'client.ui')
_gtk_objects = {}
_builder = Gtk.Builder()

def get_object(gtk_object):
	if not _gtk_objects:
		_builder.add_from_file(gtk_builder_file)
	if gtk_object in _gtk_objects:
		print('--------found gtk object----------')
		return _gtk_objects[gtk_object]
	else:
		print('adding {} gtk object'.format(gtk_object))
		_gtk_objects[gtk_object] = _builder.get_object(gtk_object)
		return _gtk_objects[gtk_object]

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
