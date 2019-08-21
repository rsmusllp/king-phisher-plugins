import argparse

from . import Plugin, phishery_inject

PARSER_EPILOG = """\
If no output file is specified, the input file will be modified in place.
"""

def main():
	parser = argparse.ArgumentParser(
		prog='phishery_docx',
		description='Phishery DOCX URL Injector Utility',
		conflict_handler='resolve'
	)
	parser.add_argument('input_file', help='the input file to inject into')
	parser.add_argument('-o', '--output', dest='output_file', help='the output file to write')
	parser.add_argument('target_urls', nargs='+', help='the target URL(s) to inject into the input file')
	parser.add_argument('-v', '--version', action='version', version='%(prog)s Version: ' + Plugin.version)
	parser.epilog = PARSER_EPILOG
	arguments = parser.parse_args()

	phishery_inject(arguments.input_file, arguments.target_urls, output_file=arguments.output_file)

if __name__ == '__main__':
	main()
