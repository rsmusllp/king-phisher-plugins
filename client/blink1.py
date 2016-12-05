import king_phisher.client.gui_utilities as gui_utilities
import king_phisher.client.plugins as plugins
import king_phisher.client.server_events as server_events

from gi.repository import GLib

try:
	from blink1 import blink1
	import usb.core
except ImportError:
	has_blink1 = False
else:
	has_blink1 = True

class Plugin(plugins.ClientPlugin):
	authors = ['Spencer McIntyre']
	title = 'Blink(1) Notifications'
	description = """
	A plugin which will flash a Blink(1) peripheral based on campaign events.
	"""
	homepage = 'https://github.com/securestate/king-phisher-plugins'
	req_min_version = '1.6.0b0'
	req_packages = {
		'blink1': has_blink1
	}
	def initialize(self):
		self._color = None
		try:
			self._blink1 = blink1.Blink1()
			self._blink1_off()
		except usb.core.USBError as error:
			gui_utilities.show_dialog_error(
				'Connection Error',
				self.application.get_active_window(),
				'Unable to connect to the Blink(1) device.'
			)
			return False
		except blink1.BlinkConnectionFailed:
			gui_utilities.show_dialog_error(
				'Connection Error',
				self.application.get_active_window(),
				'Unable to find the Blink(1) device.'
			)
			return False
		self._gsrc_id = None
		if self.application.server_events is None:
			self.signal_connect('server-connected', lambda app: self._connect_server_events())
		else:
			self._connect_server_events()
		return True

	def finalize(self):
		self._blink1_off()
		self._blink1.close()
		self._blink1 = None

	def _blink1_set_color(self, color):
		self._blink1.fade_to_color(375, color)
		if color != 'black':
			if self._gsrc_id is not None:
				GLib.source_remove(self._gsrc_id)
			self._gsrc_id = GLib.timeout_add(1625, self._blink1_off)
		self._color = color

	def _blink1_off(self):
		self._blink1_set_color('black')
		self._color = None

	def _blink1_off_timeout(self):
		self._gsrc_id = None
		self._blink1_off()
		return False

	def _connect_server_events(self):
		self.signal_connect_server_event(
			'db-credentials',
			self.signal_db_credentials,
			('inserted',),
			('id', 'campaign_id')
		)
		self.signal_connect_server_event(
			'db-visits',
			self.signal_db_visits,
			('inserted',),
			('id', 'campaign_id')
		)
		return True

	@server_events.event_type_filter('inserted', is_method=True)
	def signal_db_credentials(self, _, event_type, objects):
		self._blink1_set_color('blue')

	@server_events.event_type_filter('inserted', is_method=True)
	def signal_db_visits(self, _, event_type, objects):
		self._blink1_set_color('cyan')
