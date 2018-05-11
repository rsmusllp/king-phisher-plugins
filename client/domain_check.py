import king_phisher.client.plugins as plugins
import king_phisher.client.gui_utilities as gui_utilities

import dns.resolver

try:
	import whois
except ImportError:
	has_python_whois = False
else:
	has_python_whois = True

def domain_has_mx_record(domain):
	try:
		dns.resolver.query(domain, 'MX')
	except dns.exception.DNSException:
		return False
	return True

class Plugin(plugins.ClientPlugin):
	authors = ['Jeremy Schoeneman']
	classifiers = ['Plugin :: Client :: Email :: Spam Evasion']
	title = 'Domain Validator'
	description = """
	Checks to see if a domain can be resolved and then looks up the WHOIS
	information for it. Good for email spoofing and
	bypassing some spam filters.
	"""
	homepage = 'https://github.com/securestate/king-phisher-plugins'
	version = '1.0.2'
	req_packages = {
		'python-whois': has_python_whois
	}
	def initialize(self):
		mailer_tab = self.application.main_tabs['mailer']
		self.signal_connect('send-precheck', self.signal_precheck, gobject=mailer_tab)
		return True

	def signal_precheck(self, mailer_tab):
		email = str(self.application.config['mailer.source_email'])
		user, _, domain = email.partition('@')
		self.logger.debug("checking email domain: {0}".format(domain))

		if not domain_has_mx_record(domain):
			response = gui_utilities.show_dialog_yes_no(
				'Invalid Email Domain',
				self.application.get_active_window(),
				'The source email domain does not exist. Continue?'
			)
			if not response:
				return False

		text_insert = mailer_tab.tabs['send_messages'].text_insert
		text_insert("Checking the WHOIS record for domain '{0}'... ".format(domain))
		try:
			info = whois.whois(domain)
		except Exception as error:
			text_insert("done, encountered exception: {0}.\n".format(error.__class__.__name__))
			self.logger.error("whois lookup failed for domain: {0}".format(domain), exc_info=True)
			response = gui_utilities.show_dialog_info(
				'Whois Lookup Failed',
				self.application.get_active_window(),
				'The domain is valid, however the whois lookup failed. Continue?'
			)
			return response

		if any(info.values()):
			text_insert('done, record found.\nWHOIS Record Overview:\n')
			text_insert("  Domain registered to: {0!r}\n".format(info.name))
			if info.name_servers:
				text_insert("  Name Servers:         {0}\n".format(', '.join(info.name_servers)))
			if info.emails:
				text_insert("  Contact Email:        {0}\n".format(info.emails))
		else:
			text_insert('done, no record found.\n')
		return True
