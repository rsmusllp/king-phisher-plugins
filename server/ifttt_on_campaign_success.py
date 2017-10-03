import collections

import king_phisher.plugins as plugin_opts
import king_phisher.server.plugins as plugins
import king_phisher.server.signals as signals

import requests

EXAMPLE_CONFIG = """\
  api_key: <api_key>
  event_name: party-time
  success_percentage: 10
"""

class Plugin(plugins.ServerPlugin):
	authors = ['Spencer McIntyre']
	title = 'IFTTT Campaign Success Notification'
	description = """
	A plugin that will publish an event to a specified IFTTT Maker channel when
	a campaign has been deemed 'successful'.
	"""
	homepage = 'https://github.com/securestate/king-phisher-plugins'
	options = [
		plugin_opts.OptionString(
			name='api_key',
			description='Maker channel API key'
		),
		plugin_opts.OptionString(
			name='event_name',
			description='Maker channel Event name'
		)
	]
	def initialize(self):
		signals.db_session_inserted.connect(self.on_kp_db_event, sender='visits')
		return True

	def on_kp_db_event(self, sender, targets, session):
		campaign_ids = collection.deque()
		for event in targets:
			cid = event.campaign_id
			if cid in campaign_ids:
				continue
			if not self.check_campaign(session, cid):
				continue
			campaign_ids.append(cid)
			self.send_notification()

	def check_campaign(self, session, cid):
		campaign = db_manager.get_row_by_id(session, db_models.Campaign, cid)
		if campaign.has_expired:
			# the campaign can not be exipred
			return False

		unique_targets = session.query(models.Message.target_email)
		unique_targets = unique_targets.filter_by(campaign_id=cid)
		unique_targets = float(unique_targets.distinct().count())
		if unique_targets < 5:
			# the campaign needs at least 5 unique targets
			return False

		success_percentage = 0.25
		unique_visits = session.query(models.Visit.message_id)
		unique_visits = unique_visits.filter_by(campaign_id=cid)
		unique_visits = float(unique_visits.distinct().count())
		if unique_visits / unique_targets < success_percentage:
			# the campaign is not yet classified as successful
			return False
		if (unique_visits - 1) / unique_targets >= success_percentage:
			# the campaign has already been classified as successful
			return False
		return True

	def send_notification(self):
		try:
			resp = requests.post("https://maker.ifttt.com/trigger/{0}/with/key/{1}".format(self.config['event_name'], self.config['api_key']))
		except Exception as error:
			self.logger.error('failed to post a notification of a successful campaign (exception)', exc_info=True)
			return
		if not resp.ok:
			self.logger.error('failed to post a notification of a successful campaign (request)')
			return
		self.logger.info('successfully posted notification of a successful campaign')
