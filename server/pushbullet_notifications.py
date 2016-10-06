import logging
import re

import king_phisher.plugins as plugin_opts
import king_phisher.server.database.manager as db_manager
import king_phisher.server.database.models as db_models
import king_phisher.server.plugins as plugins
import king_phisher.server.signals as signals

try:
	from pushbullet import Pushbullet
except ImportError:
	has_pushbullet = False
else:
	has_pushbullet = True


class Plugin(plugins.ServerPlugin):
	authors = ['Brandan Geise']
	title = 'Pushbullet'
	description = """
	A plugin that uses Pushbullet's API to send push notifications
	on new website visits and submitted credentials.
	"""
	homepage = 'https://github.com/securestate/king-phisher-plugins'
	options = [
		plugin_opts.OptionString(
			name='api_keys',
			description='Pushbullet API key, if multiple, seperate with comma'
		),
		plugin_opts.OptionBoolean(
			name='mask',
			description='Partially mask email and campaign values',
			default=False
		)
	]
	req_min_version = '1.4.0b0'
	req_packages = {
		'pushbullet': has_pushbullet
	}

	def initialize(self):
		logger = logging.getLogger('pushbullet')
		logger.setLevel(logging.INFO)
		signals.server_initialized.connect(self.on_server_initialized)
		return True

	def on_server_initialized(self, server):
		signals.db_session_inserted.connect(self.on_kp_db_event, sender='visits')
		signals.db_session_inserted.connect(self.on_kp_db_event, sender='credentials')
		self.send_notification('Pushbullet notifications are now active')

	def on_kp_db_event(self, sender, targets, session):
		for event in targets:
			message = db_manager.get_row_by_id(session, db_models.Message, event.message_id)
			target_email, campaign_name = self.check_mask(message)

			if sender == 'visits':
				message = "New visit from {0} for campaign '{1}'".format(target_email, campaign_name)
			elif sender == 'credentials':
				message = "New credentials received from {0} for campaign '{1}'".format(target_email, campaign_name)
			else:
				return

			self.send_notification(message)

	def check_mask(self, message):
		if self.config['mask']:
			target_email = self.mask_string(message.target_email)
			campaign_name = self.mask_string(message.campaign.name)
		else:
			target_email = message.target_email
			campaign_name = message.campaign.name

		return target_email, campaign_name

	def mask_string(self, word):
		email_address = re.match(r'[a-z0-9._-]{1,}@[a-z0-9-]{1,}\.[a-z]{2,}', word, re.I)
		if email_address:
			email_user, email_domain = split.word('@')
			safe_string = "{0}@{1}{2}{3}".format(email_user, email_domain[:1], ('*' * (len(email_domain) - 2)), email_domain[-1:])
		else:
			safe_string = "{0}{1}{2}".format(word[:1], ('*' * (len(word) - 2)), word[-1:])

		return safe_string

	def send_notification(self, message):
		api_keys = tuple(k.strip() for k in self.config['api_keys'].split(', '))
		for key in api_keys:
			pb = Pushbullet(key)
			pb.push_note('King Phisher', message)
