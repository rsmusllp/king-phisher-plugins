import logging
import threading
import os

from king_phisher.client import gui_utilities

from gi.repository import Gtk
from gi.repository import GLib
from gi.repository import GObject

logger = logging.getLogger('KingPhisher.Plugins.SFTPClient.utilities')
GTYPE_LONG = GObject.type_from_name('glong')
GTYPE_ULONG = GObject.type_from_name('gulong')
gtk_builder_file = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'sftp_client.ui')
_gtk_objects = {}
_builder = None

def get_object(gtk_object):
	"""
	Used to maintain a diction of GTK objects to share through the SFTP Client

	:param str gtk_object: The name of the GTK Object to fetch
	:return: The requested gtk object
	"""
	global _builder
	if not _builder:
		_builder = Gtk.Builder()
	if not _gtk_objects:
		_builder.add_from_file(gtk_builder_file)
	if gtk_object in _gtk_objects:
		return _gtk_objects[gtk_object]
	else:
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
