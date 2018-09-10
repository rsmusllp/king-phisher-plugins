import datetime
import os

import king_phisher.plugins as plugin_opts
import king_phisher.templates as templates
import king_phisher.server.plugins as plugins
import king_phisher.server.signals as signals

try:
	from smtp2go import core as smtp2go
except ImportError:
	has_smtp2go = False
else:
	has_smtp2go = True

EXAMPLE_CONFIG = """\
  api_key: <api_key>
  server_email: <notifications@your_domain.com>
  email_jinja_template: <path>
"""

class Plugin(plugins.ServerPlugin):
	authors = ['Spencer McIntyre', 'Mike Stringer']
	classifiers = ['Plugin :: Server :: Notifications :: Alerts']
	title = 'Campaign Alerts: via SMTP2Go'
	description = """
	Send campaign alerts via the SMTP2go lib. This requires that users specify
	their email through the King Phisher client to subscribe to notifications.
	"""
	homepage = 'https://github.com/securestate/king-phisher-plugins'
	version = '1.1'
	options = [
		plugin_opts.OptionString(
			name='api_key',
			description='SMTP2GO API Key'
		),
		plugin_opts.OptionString(
			name='server_email',
			description='Server email address to send notifications from'
		),
		plugin_opts.OptionString(
			name='email_jinja_template',
			description='Custom email jinja template to use for alerts',
			default=''
		),
	]
	req_min_version = '1.12.0b2'
	req_packages = {
		'smtp2go': has_smtp2go
	}
	def initialize(self):
		signals.campaign_alert.connect(self.on_campaign_alert)
		template_path = self.config['email_jinja_template']
		if not template_path:
			template_path = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'template.html')
		if not os.path.isfile(template_path):
			self.logger.warning('invalid email template: ' + template_path)
			return False
		with open(template_path, 'r') as file_:
			template_data = file_.read()
		self.render_template = templates.TemplateEnvironmentBase().from_string(template_data)
		return True

	def on_campaign_alert(self, table, alert_subscription, count):
		user = alert_subscription.user
		if not user.email_address:
			self.logger.debug("user {0} has no email address specified, skipping SMTP alert".format(user.id))
			return False

		# Workaround for python-smtp2go API, which forces the use of environment variables
		# https://github.com/smtp2go-oss/smtp2go-python/pull/1 has been submitted to fix this and should eventually be replaced with...
		# api = smtp2go.Smtp2goClient(self.config['api_key']
		os.environ['SMTP2GO_API_KEY'] = self.config['api_key']
		api = smtp2go.Smtp2goClient()
		server_email = self.config['server_email']

		try:
			rendered_email = self.render_template.render(self.get_template_vars(alert_subscription))
		except:
			self.logger.warning('failed to render the email template', exc_info=True)
			return False
		payload = {
			'sender': server_email,
			'recipients': [user.email_address],
			'subject': 'Campaign Event: ' + alert_subscription.campaign.name,
			'text': 'This message requires an HTML aware email agent to be properly viewed.\r\n\r\n',
			'html': rendered_email,
			'custom_headers': {}
		}
		response = api.send(**payload)

		if not response.success:
			if response.errors:
				self.logger.error(repr([err for err in response.errors]))
			return False
		self.logger.debug("sent an email alert to user {0}".format(user.id))
		return True

	def get_template_vars(self, alert_subscription):
		campaign = alert_subscription.campaign
		template_vars = {
			'campaign': {
				'id': str(campaign.id),
				'name': campaign.name,
				'created': campaign.created,
				'expiration': campaign.expiration,
				'has_expired': campaign.has_expired,
				'message_count': len(campaign.messages),
				'visit_count': len(campaign.visits),
				'credential_count': len(campaign.credentials)
			},
			'time': {
				'local': datetime.datetime.now(),
				'utc': datetime.datetime.utcnow()
			}
		}
		return template_vars
