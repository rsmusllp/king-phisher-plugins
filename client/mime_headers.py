import distutils.version
import re

import king_phisher.version as version
import king_phisher.client.plugins as plugins

_min_version = '1.9.0b5'
StrictVersion = distutils.version.StrictVersion
api_compatible = StrictVersion(version.distutils_version) >= StrictVersion(_min_version)

class MimeHeaderParseError(ValueError):
	def __init__(self, message, header_line):
		super(MimeHeaderParseError, self).__init__(message, header_line)
		self.message = message
		self.header_line = header_line

class Plugin(plugins.ClientPlugin):
	authors = ['Spencer McIntyre']
	title = 'Custom Message MIME Headers'
	description = """
	Add custom MIME headers to messages that are sent. This can, for example be
	used to add a Sender and / or a Return-Path header to outgoing messages.
	Headers are rendered as template strings and can use variables that are
	valid in messages.
	"""
	homepage = 'https://github.com/securestate/king-phisher-plugins'
	options = [
		plugins.ClientOptionString(
			'headers',
			'The MIME headers to add to each\nof the messages, one per line.',
			display_name='MIME Headers',
			**({'multiline': True} if api_compatible else {})
		)
	]
	req_min_version = _min_version
	version = '1.0'
	_headers_split_regex = re.compile('^(?P<header>[\w-]+):\s*(?P<value>.+)?$')
	def initialize(self):
		mailer_tab = self.application.main_tabs['mailer']
		self.signal_connect('send-message', self.signal_send_message, gobject=mailer_tab)
		self.signal_connect('send-precheck', self.signal_send_precheck, gobject=mailer_tab)
		return True

	def get_headers(self, target=None):
		headers = self.config.get('headers').split('\n')
		for header_line in headers:
			header_line = header_line.strip()
			if not header_line:
				continue
			rendered_header_line = self.render_template_string(header_line, target=target, description='header line', log_to_mailer=False)
			if rendered_header_line is None:
				raise MimeHeaderParseError('failed to render', header_line)
			match = self._headers_split_regex.match(rendered_header_line)
			if match is None:
				raise MimeHeaderParseError('failed to parse', rendered_header_line)
			yield match.group('header'), match.group('value')

	def signal_send_message(self, mailer_tab, target, message):
		for header, value in self.get_headers(target):
			message[header] = value

	def signal_send_precheck(self, _):
		try:
			headers = tuple(self.get_headers())
		except MimeHeaderParseError as error:
			mailer_tab = self.application.main_tabs['mailer']
			text_insert = mailer_tab.tabs['send_messages'].text_insert
			text_insert("Custom MIME header error ({0}): {1}\n".format(error.message, error.header_line))
			return False
		return True
