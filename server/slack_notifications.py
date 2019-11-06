import json

import king_phisher.plugins as plugin_opts
import king_phisher.server.database.manager as db_manager
import king_phisher.server.database.models as db_models
import king_phisher.server.plugins as plugins
import king_phisher.server.signals as signals
import king_phisher.utilities as utilities

try:
	import requests
except ImportError:
	has_requests = False
else:
	has_requests = True

EXAMPLE_CONFIG = """\
  webhookurl: https://hooks.slack.com/services/....
  channel: <slack channel name>
"""

class Plugin(plugins.ServerPlugin):
	authors = ['Sebastian Reitenbach']
	classifiers = ['Plugin :: Server :: Notifications']
	title = 'Slack Notifications'
	description = """
	A plugin that uses Slack Webhooks to send notifications
	on new website visits and submitted credentials to a slack channel.
        Notifications about credentials are sent with @here.
	"""
	homepage = 'https://github.com/securestate/king-phisher-plugins'
	options = [
		plugin_opts.OptionString(
			name='webhookurl',
			description='The slack webhook URL to use'
		),
		plugin_opts.OptionString(
			name='channel',
			description='the channel were notifications are supposed to go to'
		)
	]
	req_min_version = '1.4.0'
	req_packages = {
		'requests': has_requests
	}
	version = '0.1'
	def initialize(self):
		signals.server_initialized.connect(self.on_server_initialized)
		return True

	def on_server_initialized(self, server):
		signals.db_session_inserted.connect(self.on_kp_db_event, sender='visits')
		signals.db_session_inserted.connect(self.on_kp_db_event, sender='credentials')
		self.send_notification('King-Phisher Slack notifications are now active')

	def on_kp_db_event(self, sender, targets, session):
		for event in targets:
			message = db_manager.get_row_by_id(session, db_models.Message, event.message_id)

			if sender == 'visits':
				message = "New visit from {0} for campaign '{1}'".format(message.target_email, message.campaign.name)
			elif sender == 'credentials':
				message = "<!here> New credentials received from {0} for campaign '{1}'".format(message.target_email, message.campaign.name)
			else:
				return
			self.send_notification(message)

	def send_notification(self, message):
                slack_data = { 'text': message, 'channel': self.config['channel'] }
                response = requests.post(
                        self.config['webhookurl'], data=json.dumps(slack_data),
                        headers={'Content-Type': 'application/json'}
                )
