import time
import os
import paramiko
import posixpath

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
			default='/$HOME',
			display_name='Local Directory'
		),
		plugins.ClientOptionString(
			'remote_directory',
			'Directory on the Server to Upload the KPM',
			default='/usr/share',
			display_name='Remote Directory'
		)
	]
	
	def initialize(self):
		mailer_tab = self.application.main_tabs['mailer']
		self.signal_connect('send-finished', self.signal_save_kpm, gobject=mailer_tab)
		return True

	def signal_save_kpm(self, config):
		mailer_tab = self.application.main_tabs['mailer']
		username = self.application.config['server_username']
		current_time = time.strftime('%m-%d-%Y_%H:%M:%S')
		campaign_name = self.application.config['campaign_name']
		filename = username + '_' + campaign_name + '_' +  str(current_time) + '.kpm'
		
		local_directory = os.path.expandvars(self.config['local_directory'])
		local_directory = os.path.expanduser(self.config['local_directory'])
		
		local_kpm = os.path.join(local_directory, filename)
		self.logger.info( "KPM Will be Saved as:  " + local_kpm )
		config_tab = mailer_tab.tabs.get('config')
		config_prefix = config_tab.config_prefix
		config_tab.objects_save_to_config()
		message_config = {}
		config_keys = (key for key in self.config.keys() if key.startswith(config_prefix))

		for config_key in config_keys:
			message_config[config_key[7:]] = self.config[config_key]
		export.message_data_to_kpm(message_config, local_kpm)
		self.logger.info( "Saved KPM as " + local_kpm )
		self.upload_kpm(local_kpm, filename)
		return True

	def upload_kpm(self, local_kpm, filename):
		remote_directory = os.path.expandvars(self.config['remote_directory'])
		remote_directory = os.path.expanduser(remote_directory)
		target_kpm = os.path.join(remote_directory, filename)
		
		connection = self.application._ssh_forwarder
		if connection is None:
			message = 'The King Phisher client does not have an active SSH connection\n'
			message += 'to the server. The SFTP client plugin can not be used.'
			gui_utilities.show_dialog_error(
				'No SSH Connection',
				self.application.get_active_window(),
				message
			)
			return

		sftp = self.application._ssh_forwarder.client.open_sftp()
		sftp.put(local_kpm, target_kpm)
		self.logger.info( "Upload Sussessful to: " + target_kpm )

