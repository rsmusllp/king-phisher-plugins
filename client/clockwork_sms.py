import re

import king_phisher.client.plugins as plugins
import king_phisher.client.gui_utilities as gui_utilities

import requests

class Plugin(plugins.ClientPlugin):
	authors = ['Spencer McIntyre']
	title = 'Clockwork SMS'
	description = """
	Send SMS messages using the Clockwork SMS API's email gateway. While
	enabled, this plugin will automatically update phone numbers into email
	addresses for sending using the service.
	"""
	homepage = 'https://github.com/securestate/king-phisher-plugins'
	options = [
		plugins.ClientOptionString(
			'api_key',
			'Clockwork API Key',
			display_name='Clockwork SMS API Key'
		)
	]
	req_min_version = '1.4.0b0'
	_sms_number_regex = re.compile(r'^[0-9]{10,12}')
	def initialize(self):
		mailer_tab = self.application.main_tabs['mailer']
		self.signal_connect('send-precheck', self.signal_send_precheck, gobject=mailer_tab)
		self.signal_connect('send-target', self.signal_send_target, gobject=mailer_tab)
		return True

	def _get_balance(self):
		api_key = self.config['api_key']
		try:
			resp = requests.get('https://api.clockworksms.com/http/balance?key=' + api_key)
		except requests.exceptions.RequestException:
			self.logger.warning('failed to check the clockwork sms balance', exc_info=True)
			return None
		resp = resp.text.strip()
		message, details = resp.split(':', 1)
		details = details.lstrip()
		return message, details

	def signal_send_precheck(self, mailer_tab):
		api_key = self.config['api_key']
		text_insert = mailer_tab.tabs['send_messages'].text_insert
		if not api_key:
			text_insert('Invalid Clockwork SMS API key.\n')
			return False

		resp = self._get_balance()
		if resp is None:
			text_insert('Failed to check the Clockwork SMS API key.\n')
			return False
		message, details = resp

		if message.lower().startswith('error'):
			self.logger.warning('received ' + message + ' (' + details + ') from clockwork api')
			text_insert("Received {0}: ({1}) from Clockwork SMS API.\n".format(message, details))
			return False
		if message.lower() != 'balance':
			self.logger.warning('received unknown response from clockwork api')
			text_insert('Received an unknown response from the Clockwork SMS API.\n')
			return False
		text_insert('Current Clockwork SMS API balance: ' + details + '\n')
		return True

	def signal_send_target(self, mailer_tab, target):
		if self._sms_number_regex.match(target.email_address) is None:
			return
		target.email_address = target.email_address + '@' + self.config['api_key'] + '.clockworksms.com'
