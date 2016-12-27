import time
import os
import paramiko

import king_phisher.client.plugins as plugins
import king_phisher.client.gui_utilities as gui_utilities
import king_phisher.client.export as export

class Plugin(plugins.ClientPlugin):
	authors = ['Jeremy Schoeneman']
	title = 'Upload KPM'
	description = """
	Saves a KPM file to the king-phisher server when sent
	Must have keyed authentication enabled to save KPM to server
	Also must have write permissions to the folder you're uploading to
	"""
	
	homepage = 'https://github.com/securestate/king-phisher-plugins'

	options = [
		plugins.ClientOptionString(
			'local_directory',
			'Local directory to save KPM File',
			default='/$HOME/',
			display_name='Local Directory'
		),
		plugins.ClientOptionString(
			'remote_directory',
			'Directory on the Server to Upload the KPM',
			default='/usr/share/',
			display_name='Remote Directory'
		),
		plugins.ClientOptionString(
			'key_path',
			'Path to Pub SSH Key',
			default='$HOME/.ssh/id_rsa.pub',
			display_name='SSH Key Path'
		)
	]
	
	def initialize(self):
		mailer_tab = self.application.main_tabs['mailer']
		# self.signal_connect('send-finished', self.signal_save_kpm, gobject=mailer_tab)
		self.signal_connect('send-precheck', self.signal_save_kpm, gobject=mailer_tab)
		return True

	def signal_save_kpm(self, config):
		mailer_tab = self.application.main_tabs['mailer']
		username = self.application.config['server_username']
		current_time = time.strftime('%m-%d-%Y.%H:%M:%S')
		campaign_name = self.application.config['campaign_name']
		filename = username + '_' + campaign_name + '_' +  str(current_time) + '.kpm'
		local_kpm = self.config['local_directory'] + '/' + filename
		
		config_tab = mailer_tab.tabs.get('config')
		config_prefix = config_tab.config_prefix
		config_tab.objects_save_to_config()
		message_config = {}
		config_keys = (key for key in self.config.keys() if key.startswith(config_prefix))

		for config_key in config_keys:
			message_config[config_key[7:]] = self.config[config_key]
		export.message_data_to_kpm(message_config, local_kpm)
		self.logger.info( "Saved KPM as " + local_kpm )
		self.upload_kpm(local_kpm, filename, username)
		return True

	def upload_kpm(self, local_kpm, filename, username):
		remote = str(self.application.config['server'].split(':', 1)[0])
		port = int(self.application.config['server'].split(':', 2)[1])
		target_kpm = self.config['remote_directory'] + '/' + filename		
		key = paramiko.RSAKey.from_private_key_file(self.config['key_path'])
		
		instance = paramiko.Transport((remote, port))

		try:
			instance.connect(username = username, pkey=key)
			sftp = paramiko.SFTPClient.from_transport(instance)
			ret = sftp.put(local_kpm, target_kpm)
		except paramiko.ssh_exception.ChannelException as error:
			self.logger.error('Transferring KPM failed', error)
			err_message = "An error occured: {0}".format(error)
			gui_utilities.show_dialog_error(
				'Error',
				self.application.get_active_window(),
				err_message
			)
			return False
		else:
			instance.close()

		self.logger.info( "Upload Sussessful to: " + remote + ': ' + target_kpm )