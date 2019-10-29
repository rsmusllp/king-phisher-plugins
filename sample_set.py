import csv
import os
import pandas
import random

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
	title = 'Sample Set Generator'
	classifiers = ['Plugin :: Client :: Tool']

	description = """
	Brings in a master list and generates a sample set from said list. 
	"""
	homepage = 'https://github.com/securestate/king-phisher-plugins'
	options = [
		plugins.ClientOptionString(
			'master_csv',
			'Master list of targets to sample',
			display_name='Master CSV File'
		),
		plugins.ClientOptionString(
			'sample_file',
			'CSV file to write the sample set to',
			display_name='Sample CSV File',
			default='~/sampled.csv'
		),
		plugins.ClientOptionInteger(
			'sample_size',
			'How many targets to sample',
			display_name='Sample Size',
		)
	]
	version = '1.0'
	def initialize(self):
		self.add_menu_item('Tools > Create Sample Set', self.sample_setup)
		return True

	def sample_setup(self, _):
		self.logger.info('sample_setup reached')
		if not self.config['master_csv']:
			gui_utilities.show_dialog_error(
				'Missing Option',
				self.application.get_active_window(),
				'Please configure the "Master CSV File" option.'
			)
			return
		if not self.config['sample_file']:
			gui_utilities.show_dialog_error(
				'Missing Option',
				self.application.get_active_window(),
				'Please configure the "Sample CSV File" option.'
			)
			return
		if not self.config['sample_size']:
			gui_utilities.show_dialog_error(
				'Missing Option',
				self.application.get_active_window(),
				'Please configure the "Sample Size" option.'
			)	
			return	
		self.logger.info('Config passed')
		
		outfile = self.expand_path(self.config['sample_file'])
		infile = self.expand_path(self.config['master_csv'])
		
		sample_set = []
		
		try:
			with open(self.config['master_csv']) as f:
				lines_in = enumerate(f)
				skip = sorted(random.sample(xrange(lines_in), lines_in-self.config[sample_size]))
				sample_set.append(pandas.read_csv(f, skiprows=skip))
			f.close()	
		except IOError as e:
			self.logger.error('outputting file error', e)	

		try:
			with open (outfile, 'w', newline="") as file_c:			
				writer = csv.writer(file_c, delimiter=",")
				for s in sample_set:
					writer.writerow(s)
			file_c.close()	
			self.logger.info('Sample set exported successfully')
			
		except IOError as e:
			self.logger.error('outputting file error', e)
		return 

	def expand_path(self, output_file, *args, **kwargs):
		expanded_path = _expand_path(output_file, *args, **kwargs)
		try:
			expanded_path = mailer.render_message_template(expanded_path, self.application.config)
		except jinja2.exceptions.TemplateSyntaxError as error:
			self.logger.error("jinja2 syntax error ({0}) in directory: {1}".format(error.message, output_file))
			gui_utilities.show_dialog_error('Error', self.application.get_active_window(), 'Error creating the CSV file.')
			return None
		except ValueError as error:
			self.logger.error("value error ({0}) in directory: {1}".format(error, output_file))
			gui_utilities.show_dialog_error('Error', self.application.get_active_window(), 'Error creating the CSV file.')
			return None
		return expanded_path

