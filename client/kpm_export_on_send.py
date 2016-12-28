import datetime
import os
import paramiko
import posixpath
import shutil
import tempfile
import time

import king_phisher.client.export as export
import king_phisher.client.gui_utilities as gui_utilities
import king_phisher.client.mailer as mailer
import king_phisher.client.plugins as plugins

import jinja2.exceptions

def _expand_path(path, *joins, pathmod=os.path):
	path = pathmod.expandvars(path)
	path = pathmod.expanduser(path)
	pathmod.join(path, *joins)
	return path

class Plugin(plugins.ClientPlugin):
	authors = ['Jeremy Schoeneman']
	title = 'Upload KPM'
	description = """
	Saves a KPM file to the King Phisher server when sending messages. The user
	must have write permissions to the specified directories. Both the "Local
	Directory" and "Remote Directory" options can use the variables that are
	available for use in message templates.
	"""
	homepage = 'https://github.com/securestate/king-phisher-plugins'
	options = [
		plugins.ClientOptionString(
			'local_directory',
			'Local directory to save the KPM file to',
			default='$HOME/{{ campaign.name }}_{{ time.local | strftime(\'%Y-%m-%d_%H:%M\') }}.kpm',
			display_name='Local Directory'
		),
		plugins.ClientOptionString(
			'remote_directory',
			'Directory on the server to upload the KPM file to',
			default='/usr/share/{{ campaign.name }}_{{ time.local | strftime(\'%Y-%m-%d_%H:%M\') }}.kpm',
			display_name='Remote Directory'
		)
	]
	req_min_version = '1.6.0b3'
	version = '1.1'
	def initialize(self):
		mailer_tab = self.application.main_tabs['mailer']
		self.text_insert = mailer_tab.tabs['send_messages'].text_insert
		self.signal_connect('send-precheck', self.signal_save_kpm, gobject=mailer_tab)
		return True

	def signal_save_kpm(self, mailer_tab):
		if not any((self.config['local_directory'], self.config['remote_directory'])):
			self.logger.debug('skipping exporting kpm archive due to no directories being specified')
			return True
		fd, temp_kpm_path = tempfile.mkstemp(suffix='.kpm')
		os.close(fd)

		if not mailer_tab.export_message_data(path=temp_kpm_path):
			self.logger.error('failed to export the temporary kpm file')
			self.text_insert('Failed to export the KPM file\n')
			return False

		result = True
		if self.config['local_directory'] and not self._save_local_kpm(temp_kpm_path):
			result = False
		if self.config['remote_directory'] and not self._save_remote_kpm(temp_kpm_path):
			result = False
		return result

	def _expand_path(self, path, *args, **kwargs):
		expanded_path = _expand_path(path, *args, **kwargs)
		try:
			expanded_path = mailer.render_message_template(expanded_path, self.application.config)
		except jinja2.exceptions.TemplateSyntaxError as error:
			self.logger.error("jinja2 syntax error ({0}) in directory: {1}".format(error.message, path))
			self.text_insert("Jinja2 syntax error ({0}) in directory: {1}\n".format(error.message, path))
			return None
		except ValueError as error:
			self.logger.error("value error ({0}) in directory: {1}".format(error, path))
			self.text_insert("Value error ({0}) in directory: {1}\n".format(error, path))
			return None
		return expanded_path

	def _save_local_kpm(self, local_kpm):
		target_kpm = self._expand_path(self.config['local_directory'])
		if target_kpm is None:
			return False

		try:
			shutil.copyfile(local_kpm, target_kpm)
		except Exception:
			self.logger.error('failed to save the kpm archive file to: ' + target_kpm)
			self.text_insert('Failed to save the KPM archive file to: ' + target_kpm + '\n')
			return False
		self.logger.info('kpm archive successfully saved to: ' + target_kpm)
		return True

	def _save_remote_kpm(self, local_kpm):
		target_kpm = self._expand_path(self.config['remote_directory'], pathmod=posixpath)
		if target_kpm is None:
			return False

		connection = self.application._ssh_forwarder
		if connection is None:
			self.logger.info('skipping uploading kpm archive due to the absence of an ssh connection')
			return True

		sftp = self.application._ssh_forwarder.client.open_sftp()
		try:
			sftp.put(local_kpm, target_kpm)
		except Exception:
			self.logger.error('failed to upload the kpm archive file to: ' + target_kpm)
			self.text_insert('Failed to upload the KPM archive file to: ' + target_kpm + '\n')
			return False
		self.logger.info('kpm archive successfully uploaded to: ' + target_kpm)
		return True
