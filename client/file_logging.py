import logging
import os

import king_phisher.client.application as application
import king_phisher.client.gui_utilities as gui_utilities
import king_phisher.client.plugins as plugins

# logger name value
LOGGER_NAME = ''

# log file size, in MB
LOG_FILE_SIZE = 10

class Plugin(plugins.ClientPlugin):
	authors = ['Zach Janice']
	title = 'File Logging'
	description = """
	Write the client's logs to a file in the users data directory.
	"""
	homepage = 'https://github.com/securestate/king-phisher-plugins'

	# this is the primary plugin entry point which is executed when the plugin is enabled
	def initialize(self):
		# ensure the directory for the logs exists
		log_dir = application.USER_DATA_PATH
		if not os.path.exists(log_dir):
			os.mkdir(log_dir)

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
		return True

	# this is a cleanup method to allow the plugin to close any open resources
	def finalize(self):
		# remove the logging handler from the logger and close it
		logger = logging.getLogger(LOGGER_NAME)
		logger.removeHandler(self.handler)
		self.handler.flush()
		self.handler.close()
