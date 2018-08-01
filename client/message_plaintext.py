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
	classifiers = ['Plugin :: Client :: Email :: Message Plaintext']
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

		if 'message_padding' in self.application.config['plugins']:
			proceed = gui_utilities.show_dialog_yes_no(
				'Warning: You are running a conflicting plugin!',
				self.application.get_active_window(),
				'The "message_padding" plugin conflicts with "message_plaintext" in such a way ' \
				+ 'that will cause the message padding to be revealed in the plaintext version ' \
				+ 'of the email. It is recommended you disable one of these plugins, or append ' \
				+ 'additional line breaks in the HTML to conceal it.\n\n' \
				+ 'Do you wish to continue?'
			)
			if not proceed:
				return False
		return True

	def signal_message_create(self, mailer_tab, target, message):
		for part in message.walk():
			if not part.get_content_type().startswith('text/html'):
				continue
			html_string = part.payload_string

		try:
			soup = BeautifulSoup(html_string, 'html.parser')
		except NameError:
			self.logger.error('unable to generate plaintext message from HTML')
			return False

		plaintext_payload_string = soup.get_text()
		for a in soup.find_all('a', href=True):
			if 'mailto:' not in a.string:
				plaintext_payload_string = plaintext_payload_string.replace(a.string, a['href'])
		for part in message.walk():
			if not part.get_content_type().startswith('text/plain'):
				continue
			part.payload_string = plaintext_payload_string
			self.logger.debug('plaintext modified from html successfully')
