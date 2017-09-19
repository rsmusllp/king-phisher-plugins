import argparse
import os
import xml.etree.ElementTree as ElementTree
import zipfile

import king_phisher.archive as archive
import king_phisher.client.plugins as plugins

PARSER_EPILOG = """\
If no output file is specified, the input file will be modified in place.
"""

def path_is_office_file(path):
	if os.path.splitext(path)[1] not in ('.docm', '.docx', '.pptm', '.pptx', '.xlsm', '.xlsx'):
		return False
	if not zipfile.is_zipfile(path):
		return False
	return True

def remove_office_metadata(input_file, output_file=None):
	"""
	Remove all metadata from Microsoft Office 2007+ file types such as docx,
	pptx, and xlsx.
	"""
	input_file = os.path.abspath(input_file)
	patches = {}
	ns = {
		'cp': 'http://schemas.openxmlformats.org/package/2006/metadata/core-properties',
		'dc': 'http://purl.org/dc/elements/1.1/',
		'dcterms': 'http://purl.org/dc/terms/',
		'dcmitype': 'http://purl.org/dc/dcmitype/',
		'xsi': 'http://www.w3.org/2001/XMLSchema-instance'
	}
	for prefix, uri in ns.items():
		ElementTree.register_namespace(prefix, uri)

	with zipfile.ZipFile(input_file, 'r') as zin:
		docprops_core = zin.read('docProps/core.xml')
	root = ElementTree.fromstring(docprops_core)
	root.clear()
	docprops_core = ElementTree.tostring(root, 'utf-8')
	patches['docProps/core.xml'] = docprops_core
	archive.patch_zipfile(input_file, patches, output_file=output_file)

class Plugin(getattr(plugins, 'ClientPluginMailerAttachment', plugins.ClientPlugin)):
	authors = ['Spencer McIntyre']
	title = 'Office 2007+ Document Metadata Remover'
	description = """
	Remove metadata from Microsoft Office 2007+ file types. These files types
	generally use the extension docx, pptx, xlsx etc. If the attachment file is
	not an Office 2007+ file, this plugin does not modify it or block the
	sending operation.
	"""
	homepage = 'https://github.com/securestate/king-phisher-plugins'
	req_min_version = '1.9.0b3'
	version = '1.0'
	def initialize(self):
		mailer_tab = self.application.main_tabs['mailer']
		self.text_insert = mailer_tab.tabs['send_messages'].text_insert
		self.signal_connect('send-precheck', self.signal_send_precheck, gobject=mailer_tab)
		return True

	def process_attachment_file(self, input_path, output_path, target=None):
		if not path_is_office_file(input_path):
			return
		remove_office_metadata(input_path, output_file=output_path)
		self.logger.info('wrote the scrubbed office document to: ' + output_path)

	def signal_send_precheck(self, _):
		input_path = self.application.config['mailer.attachment_file']
		if path_is_office_file(input_path):
			self.text_insert('Attachment file detected as MS Office 2007+, metadata will be removed.\n')
		return True

def main():
	parser = argparse.ArgumentParser(description='Office 2007+ Document Metadata Remover Utility', conflict_handler='resolve')
	parser.add_argument('-i', '--input', dest='input_file', required=True, help='the input file whose metadata is to be removed')
	parser.add_argument('-o', '--output', dest='output_file', help='the output file to write')
	parser.epilog = PARSER_EPILOG
	arguments = parser.parse_args()

	remove_office_metadata(arguments.input_file, output_file=arguments.output_file)

if __name__ == '__main__':
	main()
