import datetime
import logging
import os

import king_phisher.client.application as application
import king_phisher.client.dialogs.exception as exception
import king_phisher.client.gui_utilities as gui_utilities
import king_phisher.client.plugins as plugins

# logger name value
LOGGER_NAME = ''

# log file size, in MB
LOG_FILE_SIZE = 10

class Plugin(plugins.ClientPlugin):
	authors = ['Zach Janice', 'Spencer McIntyre']
	classifiers = ['Plugin :: Client :: Tool']
	title = 'File Logging'
	description = """
	Write the client's logs to a file in the users data directory. Additionally
	if an unhandled exception occurs, the details will be written to a dedicated
	directory.
	"""
	homepage = 'https://github.com/securestate/king-phisher-plugins'
	req_min_version = '1.6.0'
	version = '2.0'
	# this is the primary plugin entry point which is executed when the plugin is enabled
	def initialize(self):
		# ensure the directory for the logs exists
		log_dir = application.USER_DATA_PATH
		if not os.path.exists(log_dir):
			os.mkdir(log_dir)

		self.exception_dir = os.path.join(log_dir, 'exceptions')
		# ensure that the directory for exceptions exists
		if not os.path.exists(self.exception_dir):
			os.mkdir(self.exception_dir)

		# convert the specified log file size (MB) to bytes for use by the logger
		file_size = LOG_FILE_SIZE * 1024 * 1024

		# grab the logger in use by the client (root logger)
		logger = logging.getLogger(LOGGER_NAME)

		# set up the handler and formatter for the logger, and attach the components
		handler = logging.handlers.RotatingFileHandler(os.path.join(log_dir, 'king-phisher.log'), maxBytes=file_size, backupCount=2)
		formatter = logging.Formatter('%(asctime)s %(name)-50s %(levelname)-8s %(message)s')
		handler.setFormatter(formatter)
		logger.addHandler(handler)

		# keep reference of handler as an attribute
		self.handler = handler
		self.signal_connect('unhandled-exception', self.signal_kpc_unhandled_exception)
		return True

	# this is a cleanup method to allow the plugin to close any open resources
	def finalize(self):
		# remove the logging handler from the logger and close it
		logger = logging.getLogger(LOGGER_NAME)
		logger.removeHandler(self.handler)
		self.handler.flush()
		self.handler.close()

	def signal_kpc_unhandled_exception(self, _, exc_info, error_uid):
		exc_type, exc_value, exc_traceback = exc_info
		details = exception.format_exception_details(exc_type, exc_value, exc_traceback, error_uid=error_uid)
		filename = os.path.join(self.exception_dir, "{0:%Y-%m-%d_%H:%M}_{1}.txt".format(datetime.datetime.now(), error_uid))
		with open(filename, 'w') as file_h:
			file_h.write(details)
