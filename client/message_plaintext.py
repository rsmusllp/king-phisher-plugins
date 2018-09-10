import king_phisher.client.plugins as plugins
import king_phisher.client.gui_utilities as gui_utilities

try:
	from bs4 import BeautifulSoup
except ImportError:
	has_bs4 = False
else:
	has_bs4 = True

class Plugin(plugins.ClientPlugin):
	authors = ['Mike Stringer']
	classifiers = ['Plugin :: Client :: Email :: Spam Evasion']
	title = 'Message Plaintext'
	description = """
	Parse and include a plaintext version of an email based on the HTML version.
	"""
	homepage = 'https://github.com/securestate/king-phisher-plugins'
	options = []
	req_min_version = '1.10.0'
	version = '1.0'
	req_packages = {
		'bs4' : has_bs4
	}
	def initialize(self):
		mailer_tab = self.application.main_tabs['mailer']
		self.signal_connect('message-create', self.signal_message_create, gobject=mailer_tab)
		self.signal_connect('send-precheck', self.signal_send_precheck, gobject=mailer_tab)
		return True

	def signal_message_create(self, mailer_tab, target, message):
		html_part = next((part for part in message.walk() if part.get_content_type().startswith('text/html')), None)
		if html_part is None:
			self.logger.error('unable to generate plaintext message from HTML (failed to find text/html part)')
			return False
		text_part = next((part for part in message.walk() if part.get_content_type().startswith('text/plain')), None)
		if text_part is None:
			self.logger.error('unable to generate plaintext message from HTML (failed to find text/plain part)')
			return False

		soup = BeautifulSoup(html_part.payload_string, 'html.parser')
		plaintext_payload_string = soup.get_text()
		for a in soup.find_all('a', href=True):
			if 'mailto:' not in a.string:
				plaintext_payload_string = plaintext_payload_string.replace(a.string, a['href'])
		text_part.payload_string = plaintext_payload_string
		self.logger.debug('plaintext modified from html successfully')

	def signal_send_precheck(self, mailer_tab):
		if 'message_padding' not in self.application.plugin_manager.enabled_plugins:
			return True
		proceed = gui_utilities.show_dialog_yes_no(
			'Warning: You are running a conflicting plugin!',
			self.application.get_active_window(),
			'The "message_padding" plugin conflicts with "message_plaintext" in such a way '\
			+ 'that will cause the message padding to be revealed in the plaintext version '\
			+ 'of the email. It is recommended you disable one of these plugins, or append '\
			+ 'additional line breaks in the HTML to conceal it.\n\n' \
			+ 'Do you wish to continue?'
		)
		return proceed
