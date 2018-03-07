import king_phisher.client.plugins as plugins

GTUBE = 'XJS*C4JDBQADN1.NSBN3*2IDNEN*GTUBE-STANDARD-ANTI-UBE-TEST-EMAIL*C.34X'

class Plugin(plugins.ClientPlugin):
	authors = ['Spencer McIntyre']
	title = 'GTUBE Header'
	description = """
	Add the Generic Test for Unsolicited Bulk Email (GTUBE) string as a X-GTUBE
	header and append it to the end of all text/* parts of the MIME messages
	that are sent.

	This will cause messages to be identified as SPAM.
	"""
	homepage = 'https://github.com/securestate/king-phisher-plugins'
	req_min_version = '1.10.0b3'
	version = '1.0'
	def initialize(self):
		mailer_tab = self.application.main_tabs['mailer']
		self.signal_connect('message-create', self.signal_message_create, gobject=mailer_tab)
		return True

	def signal_message_create(self, mailer_tab, target, message):
		message['X-GTUBE'] = GTUBE
		for part in message.walk():
			if not part.get_content_type().startswith('text/'):
				continue
			part.payload_string = part.payload_string + '\n' + GTUBE + '\n'
