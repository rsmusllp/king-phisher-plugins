import king_phisher.plugins as plugin_opts
import king_phisher.server.plugins as plugins
import king_phisher.server.signals as signals
from os import environ


try:
	from smtp2go import core as smtp2go
except ImportError:
	has_smtp2go = False
else:
	has_smtp2go = True

EXAMPLE_CONFIG = """\
  api_key: <api_key>
  server_email: <notifications@your_domain.com>
"""


class Plugin(plugins.ServerPlugin):
	authors = ['Spencer McIntyre', 'Mike Stringer']
	title = 'Campaign Alerts: via SMTP2Go'
	description = """
	Send campaign alerts via the SMTP2go lib. This requires that users specify
	their email through the King Phisher client to subscribe to notifications.
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
		if not user.email_address:
			self.logger.debug("user {0} has no email address specified, skipping SMTP alert".format(user.id))
			return False
		# Workaround for python-smtp2go API, which forces the use of environment variables
		# https://github.com/smtp2go-oss/smtp2go-python/pull/1 has been submitted to fix this and should eventually be replaced with...
		# api = smtp2go.Smtp2goClient(self.config['api_key']
		environ['SMTP2GO_API_KEY'] = self.config['api_key']
		api = smtp2go.Smtp2goClient()
		server_email = self.config['server_email']

		message = "{0:,} {1} reached for campaign: {2}".format(count, table.replace('_', ' '), alert_subscription.campaign.name)
		payload = {
			'sender' : server_email,
			'recipients' : user.email_address,
			'subject' : 'Campaign Event: ' + alert_subscription.campaign.name,
			'text' : message,
			'html' : "<html><body><h1>Campain Event: {0}</h1><p>{1}</p></body></html>".format(alert_subscription.campaign.name, message),
			'custom_headers' : {}
		}
		response = api.send(**payload)

		if not response.success:
			if response.errors:
				self.logger([err for err in response.errors])
			return False
		self.logger.debug("sent an email alert to user {0}".format(user.id))
		return True
