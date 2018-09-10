import datetime
import os
import smtplib
import socket

import king_phisher.plugins as plugin_opts
import king_phisher.server.plugins as plugins
import king_phisher.server.signals as signals
import king_phisher.templates as templates

from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

EXAMPLE_CONFIG = """
  smtp_server: <smtp.server.com>
  smtp_port: <port>
  smtp_email: <source_email>
  smtp_username: <username>
  smtp_password: <password>
  smtp_ssl: <boolean>
  email_jinja_template: <path>
"""

class Plugin(plugins.ServerPlugin):
	authors = ['Austin DeFrancesco', 'Spencer McIntyre', 'Mike Stringer', 'Erik Daguerre']
	classifiers = ['Plugin :: Server :: Notifications :: Alerts']
	title = 'Campaign Alerts: via Python 3 SMTPLib'
	description = """
	Send campaign alerts via the SMTP Python 3 lib. This requires that users specify
	their email through the King Phisher client to subscribe to notifications.
	"""
	homepage = 'https://github.com/securestate/king-phisher-plugins'
	version = '1.1'

	# Email accounts with 2FA, such as Gmail, will not work unless "less secure apps" are allowed
	# Reference: https://support.google.com/accounts/answer/60610255
	# Gmail and other providers require SSL on port 465, TLS will start with the activation of SSL
	options = [
		plugin_opts.OptionString(
			name='smtp_server',
			description='Location of SMTP server',
			default='localhost'
		),
		plugin_opts.OptionInteger(
			name='smtp_port',
			description='Port used for SMTP server',
			default=25
		),
		plugin_opts.OptionString(
			name='smtp_email',
			description='SMTP email address to send notifications from',
			default=''
		),
		plugin_opts.OptionString(
			name='smtp_username',
			description='Username to authenticate to the SMTP server with'
		),
		plugin_opts.OptionString(
			name='smtp_password',
			description='Password to authenticate to the SMTP server with',
			default=''
		),
		plugin_opts.OptionBoolean(
			name='smtp_ssl',
			description='Connect to the SMTP server with SSL',
			default=False
		),
		plugin_opts.OptionString(
			name='email_jinja_template',
			description='Custom email jinja template to use for alerts',
			default=''
		),
	]
	req_min_version = '1.12.0b2'
	def initialize(self):
		signals.campaign_alert.connect(self.on_campaign_alert)
		signals.campaign_alert_expired.connect(self.on_campaign_alert_expired)
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
		return self.send_alert(alert_subscription)

	def on_campaign_alert_expired(self, camapign, alert_subscription):
		return self.send_alert(alert_subscription)

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

	def create_message(self, alert_subscription):
		message = MIMEMultipart()
		message['Subject'] = "Campaign Event: {0}".format(alert_subscription.campaign.name)
		message['From'] = "<{0}>".format(self.config['smtp_email'])
		message['To'] = "<{0}>".format(alert_subscription.user.email_address)

		textual_message = MIMEMultipart('alternative')
		plaintext_part = MIMEText('This message requires an HTML aware email agent to be properly viewed.\r\n\r\n', 'plain')
		textual_message.attach(plaintext_part)

		try:
			rendered_email = self.render_template.render(self.get_template_vars(alert_subscription))
		except:
			self.logger.warning('failed to render the email template', exc_info=True)
			return False
		html_part = MIMEText(rendered_email, 'html')
		textual_message.attach(html_part)

		message.attach(textual_message)
		encoded_email = message.as_string()
		return encoded_email

	def send_alert(self, alert_subscription):
		user = alert_subscription.user
		if not user.email_address:
			self.logger.debug("user {0} has no email address specified, skipping SMTP alert".format(user.name))
			return False

		msg = self.create_message(alert_subscription)
		if not msg:
			return False

		if self.config['smtp_ssl']:
			SmtpClass = smtplib.SMTP_SSL
		else:
			SmtpClass = smtplib.SMTP
		try:
			server = SmtpClass(self.config['smtp_server'], self.config['smtp_port'], timeout=15)
			server.ehlo()
		except smtplib.SMTPException:
			self.logger.warning('received an SMTPException while connecting to the SMTP server', exc_info=True)
			return False
		except socket.error:
			self.logger.warning('received a socket.error while connecting to the SMTP server')
			return False

		if not self.config['smtp_ssl'] and 'starttls' in server.esmtp_features:
			self.logger.debug('target SMTP server supports the STARTTLS extension')
			try:
				server.starttls()
				server.ehlo()
			except smtplib.SMTPException:
				self.logger.warning('received an SMTPException wile negotiating STARTTLS with SMTP server', exc_info=True)
				return False

		if self.config['smtp_username']:
			try:
				server.login(self.config['smtp_username'], self.config['smtp_password'])
			except smtplib.SMTPNotSupportedError:
				self.logger.debug('SMTP server does not support authentication')
			except smtplib.SMTPException as error:
				self.logger.warning("received an {0} while authenticating to the SMTP server".format(error.__class__.__name__))
				server.quit()
				return False

		mail_options = ['SMTPUTF8'] if server.has_extn('SMTPUTF8') else []
		try:
			server.sendmail(self.config['smtp_email'], alert_subscription.user.email_address, msg, mail_options)
		except smtplib.SMTPException as error:
			self.logger.warning("received error {0} while sending mail".format(error.__class__.__name__))
			return False
		finally:
			server.quit()
		self.logger.debug("successfully sent an email campaign alert to user: {0}".format(user.name))
		return True
