import king_phisher.sms as sms
import king_phisher.server.plugins as plugins
import king_phisher.server.signals as signals

class Plugin(plugins.ServerPlugin):
	authors = ['Spencer McIntyre']
	classifiers = ['Plugin :: Server :: Notifications :: Alerts']
	title = 'Campaign Alerts: via Carrier SMS Email Gateways'
	description = """
	Send campaign alerts as SMS messages through cell carrier's email gateways.
	This requires that users supply both their cell phone number and specify a
	supported carrier through the King Phisher client.
	"""
	homepage = 'https://github.com/securestate/king-phisher-plugins'
	version = '1.1'
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
		if not user.phone_carrier:
			self.logger.debug("user {0} has no cell phone carrier specified, skipping SMS alert".format(user.name))
			return False
		if not user.phone_number:
			self.logger.debug("user {0} has no cell phone number specified, skipping SMS alert".format(user.name))
			return False
		try:
			sms.send_sms(message, user.phone_number, user.phone_carrier)
		except Exception:
			self.logger.error("failed to send the SMS alert to {0} ({1} / {2})".format(user.name, user.phone_number, user.phone_carrier), exc_info=True)
			return False
		self.logger.debug("sent an SMS alert to user {0} ({1} / {2})".format(user.name, user.phone_number, user.phone_carrier))
		return True
