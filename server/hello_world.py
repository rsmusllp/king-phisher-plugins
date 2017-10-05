import king_phisher.server.plugins as plugins
import king_phisher.server.signals as signals

EXAMPLE_CONFIG = """\
# This section should offer some insight into what this plugin expects for inputs
  example_var_1: test_1
  example_var_2: test_2
"""

class Plugin(plugins.ServerPlugin):
	authors = ['Spencer McIntyre']
	title = 'Hello World!'
	description = """
	A 'hello world' plugin to serve as a basic template and demonstration. This
	plugin will log simple messages to show that it is functioning.
	"""
	homepage = 'https://github.com/securestate/king-phisher-plugins'
	def initialize(self):
		signals.server_initialized.connect(self.on_server_initialized)
		self.logger.info('hello-world: the plugin has been initialized')
		return True

	def on_server_initialized(self, server):
		self.logger.info('hello-world: the server has been initialized')
