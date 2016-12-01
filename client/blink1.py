import king_phisher.client.gui_utilities as gui_utilities
import king_phisher.client.plugins as plugins
import king_phisher.client.server_events as server_events

try:
	from blink1 import blink1
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
		try:
			self._blink1 = blink1.Blink1()
		except blink1.BlinkConnectionFailed:
			gui_utilities.show_dialog_error(
				'Connection Error',
				self.application.get_active_window(),
				'Unable to connect to the Blink(1) device.'
			)
			return False
		self.signal_connect_server_event(
			'db-credentials',
			self.signal_db_credentials
			('inserted',),
			('id', 'campaign_id')
		)
		self.signal_connect_server_event(
			'db-visits',
			self.signal_db_vists,
			('inserted',),
			('id', 'campaign_id')
		)
		return True

	@server_events.filter_event_type('inserted')
	def signal_db_credentials(self, _, event_type, objects):
		self._blink1.fade_to_color(0, 'blue')

	@server_events.filter_event_type('inserted')
	def signal_db_visits(self, _, event_type, objects):
		self._blink1.fade_to_color(0, 'cyan')
