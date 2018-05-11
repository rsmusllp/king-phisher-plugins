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
	req_min_version = '1.10.0'
	def initialize(self):
		signals.campaign_alert.connect(self.on_campaign_alert)
		return True

	def on_campaign_alert(self, table, alert_subscription, count):
		user = alert_subscription.user
		if not user.phone_carrier:
			self.logger.debug("user {0} has no cell phone carrier specified, skipping SMS alert".format(user.id))
			return False
		if not user.phone_number:
			self.logger.debug("user {0} has no cell phone number specified, skipping SMS alert".format(user.id))
			return False

		message = "{0:,} {1} reached for campaign: {2}".format(count, table.replace('_', ' '), alert_subscription.campaign.name)
		try:
			sms.send_sms(message, user.phone_number, user.phone_carrier)
		except Exception:
			self.logger.error("failed to send the SMS alert to {0} ({1} / {2})".format(user.id, user.phone_number, user.phone_carrier), exc_info=True)
			return False
		self.logger.debug("sent an SMS alert to user {0} ({1} / {2})".format(user.id, user.phone_number, user.phone_carrier))
		return True
