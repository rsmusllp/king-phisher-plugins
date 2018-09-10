import king_phisher.plugins as plugin_opts
import king_phisher.server.plugins as plugins
import king_phisher.server.signals as signals

try:
	import clockwork
except ImportError:
	has_clockwork = False
else:
	has_clockwork = True

EXAMPLE_CONFIG = """\
  api_key: <api_key>
"""

class Plugin(plugins.ServerPlugin):
	authors = ['Spencer McIntyre']
	classifiers = ['Plugin :: Server :: Notifications :: Alerts']
	title = 'Campaign Alerts: via Clockwork SMS'
	description = """
	Send campaign alerts via the Clockwork SMS API. This requires that users
	specify their cell phone number through the King Phisher client.
	"""
	homepage = 'https://github.com/securestate/king-phisher-plugins'
	version = '1.1'
	options = [
		plugin_opts.OptionString(
			name='api_key',
			description='Clockwork SMS API Key'
		)
	]
	req_packages = {
		'clockwork': has_clockwork
	}
	req_min_version = '1.12.0b2'
	def initialize(self):
		signals.campaign_alert.connect(self.on_campaign_alert)
		signals.campaign_alert_expired.connect(self.on_campaign_alert_expired)
		return True

	def on_campaign_alert(self, table, alert_subscription, count):
		message = "Campaign '{0}' has reached {1:,} {2}".format(alert_subscription.campaign.name, count, table.replace('_', ' '))
		return self.send_alert(alert_subscription, message)

	def on_campaign_alert_expired(self, camapign, alert_subscription):
		message = "Campaign '{0}' has expired".format(alert_subscription.campaign.name)
		return self.send_alert(alert_subscription, message)

	def send_alert(self, alert_subscription, message):
		user = alert_subscription.user
		if not user.phone_number:
			self.logger.debug("user {0} has no cell phone number specified, skipping SMS alert".format(user.name))
			return False
		api = clockwork.API(self.config['api_key'])

		response = api.send(clockwork.SMS(user.phone_number, message)) 
		if not response.success:
			self.logger.error("received error {0} ({1})".format(response.error_code, response.error_message))
			return False
		self.logger.debug("sent an SMS alert to user {0}".format(user.name))
		return True
