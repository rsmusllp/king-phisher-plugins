import king_phisher.plugins as plugin_opts
import king_phisher.server.plugins as plugins
import king_phisher.server.signals as signals
from smtp2go.core import Smtp2goClient

try:
	import smtp2go
except ImportError:
	has_smtp2go = False
else:
	has_smtp2go = True

EXAMPLE_CONFIG = """\
  api_key: <api_key>
"""

class Smtp(Smtp2goClient()):
	def __init__(self, api_key):
		self.api_key = api_key		# Inherits from Smtp2goClient to avoid the superclass attempting to retrieve api_key from environment vars

class Plugin(plugins.ServerPlugin):
	authors = ['Mike Stringer', 'Spencer McIntyre']
	title = 'Campaign Alerts: via SMTP2Go'
	description = """
	Send campaign alerts via the SMTP2go lib. This requires that users specify
    their email through the King Phisher client to subscribe to notifications.
    Derived from clockwork_sms plugin by Spencer McIntyre.
	"""
	homepage = 'https://github.com/securestate/king-phisher-plugins'
	options = [
		plugin_opts.OptionString(
			name='api_key',
			description='SMTP2GO API Key'
		),
		plugin_opts.OptionString(
			name='server_email',
			description='Server email address to send notifications from'
		)
	]
	req_min_version = '1.10.0b0'
	req_packages = {
		'smtp2go': has_smtp2go
	}
	def initialize(self):
		signals.campaign_alert.connect(self.on_campaign_alert)
		return True

	def on_campaign_alert(self, table, alert_subscription, count):
		user = alert_subscription.user
		if not user.email:
			self.logger.debug("user {0} has no email address specified, skipping SMTP alert".format(user.id))
			return False
		api = smtp2go.Smtp2goClient(self.config['api_key'])
		server_email = self.config['server_email']

		message = "{0:,} {1} reached for campaign: {2}".format(count, table.replace('_', ' '), alert_subscription.campaign.name)
		response = api.send(server_email, user.email, message)

		if not response.success:
			self.logger.error("received error {0} ({1})".format(response.error_code, response.error_message))
			return False
		self.logger.debug("sent an SMS alert to user {0}".format(user.id))
		return True
