import king_phisher.client.plugins as plugins
import king_phisher.client.gui_utilities as gui_utilities

from socket import getaddrinfo

try:
	import whois
except ImportError:
	has_python_whois = False
else:
	has_python_whois = True

class Plugin(plugins.ClientPlugin):
	authors = ['Jeremy Schoeneman']
	title = 'Domain Validator'
	description = """
	Checks to see if a domain can be resolved. Good for email spoofing and
	bypassing some spam filters.
	"""
	homepage = 'https://github.com/securestate/king-phisher-plugins'
	version = '1.0.1'
	req_packages = {
		'python-whois': has_python_whois
	}
	def initialize(self):
		mailer_tab = self.application.main_tabs['mailer']
		self.signal_connect('send-precheck', self.signal_check_domain, gobject=mailer_tab)
		return True

	def signal_check_domain(self, _):
		email = str(self.application.config['mailer.source_email'])
		user, _, domain = email.partition('@')
		try:
			self.logger.debug("checking email domain: {0}".format(domain))
			result = getaddrinfo(domain, None)
			if result:
				try:
					info = whois.whois(domain)
					self.logger.info('email domain valid')
					gui_utilities.show_dialog_info(
						'Email Domain Valid',
						self.application.get_active_window(),
						'Domain registered to: ' + info.name + '\n',
						'Name Servers: ' + info.name_servers + '\n',
						'Contact Email: ' + info.emails
					)
				except Exception as err:
					self.logger.info('whois lookup unavailable')
					gui_utilities.show_dialog_info(
						'Email Domain Valid',
						self.application.get_active_window(),
						'Your domain is valid, however whois lookup failed.'
					)
			else:
				self.logger.info("email domain {0} is valid".format(domain))
		except Exception as err:
			return gui_utilities.show_dialog_yes_no('Spoofed Email Domain Does not exist, continue?', self.application.get_active_window())
		return True
