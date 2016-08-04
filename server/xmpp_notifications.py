import logging

import king_phisher.plugins as plugin_opts
import king_phisher.server.database.manager as db_manager
import king_phisher.server.database.models as db_models
import king_phisher.server.plugins as plugins
import king_phisher.server.signals as signals

import smoke_zephyr.utilities as utilities

try:
	import sleekxmpp
except ImportError:
	has_sleekxmpp = False
	_sleekxmpp_ClientXMPP = object
else:
	has_sleekxmpp = True
	_sleekxmpp_ClientXMPP = sleekxmpp.ClientXMPP

class NotificationBot(_sleekxmpp_ClientXMPP):
	def __init__(self, jid, password, room, verify_cert):
		super(NotificationBot, self).__init__(jid, password)
		self.add_event_handler('disconnect', self.on_xmpp_disconnect)
		self.add_event_handler('session_start', self.on_xmpp_session_start)
		self.add_event_handler('ssl_invalid_cert', self.on_xmpp_ssl_invalid_cert)
		self.register_plugin('xep_0030')  # service discovery
		self.register_plugin('xep_0045')  # multi-user chat
		self.register_plugin('xep_0199')  # xmpp ping
		self.room = room
		self.verify_cert = verify_cert
		self.logger = logging.getLogger('KingPhisher.Plugins.XMPPNoficationBot')

	def send_notification(self, message):
		ET = sleekxmpp.xmlstream.ET
		xhtml = ET.Element('span')
		xhtml.set('style', 'font-family: Monospace')
		message_lines = message.split('\n')
		for line in message_lines[:-1]:
			p = ET.SubElement(xhtml, 'p')
			p.text = line
			ET.SubElement(xhtml, 'br')
		p = ET.SubElement(xhtml, 'p')
		p.text = message_lines[-1]
		self.send_message(mto=self.room, mbody=message, mtype='groupchat', mhtml=xhtml)

	def on_kp_db_new_campaign(self, sender, targets, session):
		for campaign in targets:
			self.send_notification("new campaign '{0}' created by {1}".format(campaign.name, campaign.user_id))

	def on_kp_db_new_credentials(self, sender, targets, session):
		for credential in targets:
			message = db_manager.get_row_by_id(session, db_models.Message, credential.message_id)
			self.send_notification("new credentials received from {0} for campaign '{1}'".format(message.target_email, message.campaign.name))

	def on_kp_db_new_visit(self, sender, targets, session):
		for visit in targets:
			message = db_manager.get_row_by_id(session, db_models.Message, visit.message_id)
			self.send_notification("new visit received from {0} for campaign '{1}'".format(message.target_email, message.campaign.name))

	def on_xmpp_disconnect(self, _):
		signals.db_session_inserted.disconnect(self.on_kp_db_new_campaign, sender='campaigns')
		signals.db_session_inserted.disconnect(self.on_kp_db_new_credentials, sender='credentials')
		signals.db_session_inserted.disconnect(self.on_kp_db_new_visit, sender='visits')

	def on_xmpp_session_start(self, _):
		self.send_presence()
		self.get_roster()

		self.plugin['xep_0045'].joinMUC(self.room, self.boundjid.user, wait=True)

		signals.db_session_inserted.connect(self.on_kp_db_new_campaign, sender='campaigns')
		signals.db_session_inserted.connect(self.on_kp_db_new_credentials, sender='credentials')
		signals.db_session_inserted.connect(self.on_kp_db_new_visit, sender='visits')
		self.send_notification('king phisher server notifications are now online')

	def on_xmpp_ssl_invalid_cert(self, pem_cert):
		if self.verify_cert:
			self.logger.warning('received an invalid ssl certificate, disconnecting from the server')
			self.disconnect(send_close=False)
		else:
			self.logger.warning('received an invalid ssl certificate, ignoring it per the configuration')
		return

class Plugin(plugins.ServerPlugin):
	authors = ['Spencer McIntyre']
	title = 'XMPP Notifications'
	description = """
	A plugin which pushes notifications regarding the King Phisher server to a
	specified XMPP server.
	"""
	homepage = 'https://github.com/securestate/king-phisher-plugins'
	options = [
		plugin_opts.OptionString('jid', 'the username to login with'),
		plugin_opts.OptionString('password', 'the password to login with'),
		plugin_opts.OptionString('room', 'the room to send notifications to'),
		plugin_opts.OptionString('server', 'the server to connect to'),
		# verify_cert only functions when sleekxmpp supports it
		plugin_opts.OptionBoolean('verify_cert', 'verify the ssl certificate', default=True)
	]
	req_min_version = '1.4.0b0'
	req_packages = {
		'sleekxmpp': has_sleekxmpp
	}
	def initialize(self):
		logger = logging.getLogger('sleekxmpp')
		logger.setLevel(logging.INFO)
		self.bot = None
		signals.server_initialized.connect(self.on_server_initialized)
		return True

	def on_server_initialized(self, server):
		self.bot = NotificationBot(
			self.config['jid'],
			self.config['password'],
			self.config['room'],
			self.config['verify_cert']
		)
		self.bot.connect(utilities.parse_server(self.config['server'], 5222))
		self.bot.process(block=False)

	def finalize(self):
		if self.bot is None:
			return
		self.bot.disconnect()
