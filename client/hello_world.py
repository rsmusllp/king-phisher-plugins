import king_phisher.client.plugins as plugins
import king_phisher.client.gui_utilities as gui_utilities

class Plugin(plugins.ClientPlugin):
	authors = ['Spencer McIntyre']
	title = 'Hello World!'
	description = """
	A 'hello world' plugin to serve as a basic template and demonstration. This
	plugin will display a message box when King Phisher exits.
	"""
	homepage = 'https://github.com/securestate/king-phisher-plugins'
	options = [
		plugins.ClientOptionBoolean('validiction', 'Whether or not this plugin say good bye.', default=True, display_name='Say Good Bye'),
		plugins.ClientOptionString('name', 'The name to which to say goodbye.', default='Alice Liddle', display_name='Your Name')
	]
	def initialize(self):
		print('Hello World!')
		self.signal_connect('exit', self.signal_exit)
		return True

	def finalize(self):
		print('Good Bye World!')

	def signal_exit(self, app):
		if not self.config['validiction']:
			return
		gui_utilities.show_dialog_info("Good bye {0}!".format(self.config['name']), app.get_active_window())
