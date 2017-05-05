import os
import paramiko

from . import client
from . import sftp_utilities

from king_phisher.client import gui_utilities
from king_phisher.client import plugins

from gi.repository import GObject

class Plugin(plugins.ClientPlugin):
	authors = ['Josh Jacob', 'Spencer McIntyre', 'Erik Daguerre']
	title = 'SFTP Client'
	description = """
	Secure File Transfer Protocol Client that can be used to upload, download,
	create, and delete local and remote files on the King Phisher Server.
	
	The editor allows you edit files on remote or local system. It is primarily
	designed for the use of editing remote web pages on the King Phisher Server.
	"""
	homepage = 'https://github.com/securestate/king-phisher'
	req_min_version = '1.4.0b0'
	version = '1.3'
	def initialize(self):
		"""Connects to the start SFTP Client Signal to the plugin and checks for .ui file."""
		self.sftp_window = None
		if not os.access(sftp_utilities.gtk_builder_file, os.R_OK):
			gui_utilities.show_dialog_error(
				'Plugin Error',
				self.application.get_active_window(),
				"The GTK Builder data file ({0}) is not available.".format(os.path.basename(sftp_utilities.gtk_builder_file))
			)
			return False
		if 'directories' not in self.config:
			self.config['directories'] = {}
		if 'transfer_hidden' not in self.config:
			self.config['transfer_hidden'] = False
		if 'show_hidden' not in self.config:
			self.config['show_hidden'] = False
		self.signal_connect('sftp-client-start', self.signal_sftp_start)
		return True

	def finalize(self):
		"""Allows the window to be properly closed upon the deactivation of the plugin."""
		if self.sftp_window is not None:
			self.sftp_window.destroy()

	def signal_sftp_start(self, _):
		GObject.signal_stop_emission_by_name(self.application, 'sftp-client-start')
		if self.sftp_window is None:
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
			ssh = connection.client
			self.logger.debug('loading gtk builder file from: ' + sftp_utilities.gtk_builder_file)
			try:
				manager = client.FileManager(self.application, ssh, self.config)
			except paramiko.ssh_exception.ChannelException as error:
				self.logger.error('an ssh channel exception was raised while initializing', exc_info=True)
				if len(error.args) == 2:
					details = "SSH Channel Exception #{0} ({1})".format(*error.args)
				else:
					details = 'An unknown SSH Channel Exception occurred.'
				gui_utilities.show_dialog_error('SSH Channel Exception', self.application.get_active_window(), details)
				return
			except paramiko.ssh_exception.SSHException:
				self.logger.error('an ssh exception was raised while initializing', exc_info=True)
				gui_utilities.show_dialog_error('SSH Exception', self.application.get_active_window(), 'An error occurred in the SSH transport.')
				return
			self.sftp_window = manager.window
			self.sftp_window.connect('destroy', self.signal_window_destroy)
		self.sftp_window.show()
		self.sftp_window.present()

	def signal_window_destroy(self, window):
		self.sftp_window = None
