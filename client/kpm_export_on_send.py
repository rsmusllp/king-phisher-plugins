import time
import os
import paramiko
import posixpath

import king_phisher.client.plugins as plugins
import king_phisher.client.gui_utilities as gui_utilities
import king_phisher.client.export as export

def _expand_path(path, pathmod=os.path):
	path = pathmod.expandvars(path)
	path = pathmod.expanduser(path)
	return path

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
			'Local directory to save the KPM file to',
			default='$HOME',
			display_name='Local Directory'
		),
		plugins.ClientOptionString(
			'remote_directory',
			'Directory on the server to upload the KPM file to',
			default='/usr/share',
			display_name='Remote Directory'
		)
	]
	version = '1.0'
	def initialize(self):
		mailer_tab = self.application.main_tabs['mailer']
		self.text_insert = mailer_tab.tabs['send_messages'].text_insert
		self.signal_connect('send-precheck', self.signal_save_kpm, gobject=mailer_tab)
		return True

	def signal_save_kpm(self, mailer_tab):
		username = self.application.config['server_username']
		current_time = time.strftime('%m-%d-%Y_%H:%M:%S')
		campaign_name = self.application.config['campaign_name']
		filename = username + '_' + campaign_name + '_' + str(current_time) + '.kpm'
		
		local_directory = _expand_path(self.config['local_directory'])
		
		local_kpm = os.path.join(local_directory, filename)
		self.logger.info('kpm will be saved locally as:' + local_kpm)
		config_tab = mailer_tab.tabs.get('config')
		config_prefix = config_tab.config_prefix
		config_tab.objects_save_to_config()
		message_config = {}
		config_keys = (key for key in self.application.config.keys() if key.startswith(config_prefix))

		for config_key in config_keys:
			message_config[config_key[7:]] = self.application.config[config_key]
		export.message_data_to_kpm(message_config, local_kpm)
		self.logger.info('kpm archive successfully saved to: ' + local_kpm)
		self.text_insert('KPM archive saved to: ' + local_kpm + '\n')
		return self.upload_kpm(local_kpm, filename)

	def upload_kpm(self, local_kpm, filename):
		remote_directory = _expand_path(self.config['remote_directory'], pathmod=posixpath)
		target_kpm = posixpath.os.path.join(remote_directory, filename)
		
		connection = self.application._ssh_forwarder
		if connection is None:
			self.logger.info('skipping uploading kpm archive due to the absence of an ssh connection')
			return

		sftp = self.application._ssh_forwarder.client.open_sftp()
		try:
			sftp.put(local_kpm, target_kpm)
		except:
			self.logger.error('failed to upload the kpm archive file to: ' + target_kpm)
			self.text_insert('Failed to upload the KPM archive file to: ' + target_kpm + '\n')
			return False
		self.logger.info('kpm archive successfully uploaded to: ' + target_kpm)
		return True

