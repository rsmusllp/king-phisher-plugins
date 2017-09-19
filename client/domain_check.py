import king_phisher.client.plugins as plugins
import king_phisher.client.gui_utilities as gui_utilities

from socket import getaddrinfo

try:
	import whois
except ImportError:
	has_pywhois = False
else:
	has_pywhois = True

class Plugin(plugins.ClientPlugin):
	authors = ['Jeremy Schoeneman']  # the plugins author
	title = 'Domain Validator'		  # the title of the plugin to be shown to users
	description = """
	Checks to see if a domain can be resolved. Good for email spoofing and
	bypassing some spam filters.
	"""							 # a description of the plugin to be shown to users
	homepage = 'https://github.com/securestate/king-phisher-plugins'  # an optional home page
	version = '1.0'			# (optional) specify this plugin's version
	# this is the primary plugin entry point which is executed when the plugin is enabled
	req_packages = {
		'pywhois': has_pywhois
	}

	def initialize(self):
		mailer_tab = self.application.main_tabs['mailer']
		self.signal_connect('send-precheck', self.signal_check_domain, gobject=mailer_tab)
		return True

	def signal_check_domain(self, _):
		email = str(self.application.config['mailer.source_email'])
		user,at,domain = email.partition('@')
		try:
			self.logger.debug('checking email domain')
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
				self.logger.info('email domain valid')
		except Exception as err:
			if not gui_utilities.show_dialog_yes_no('Spoofed Email Domain Doesn\'t exist, continue?', self.application.get_active_window()):
				return
		return True
