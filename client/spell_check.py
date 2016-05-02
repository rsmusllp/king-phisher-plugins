import king_phisher.client.plugins as plugins

import gi
try:
	gi.require_version('GtkSpell', '3.0')
	from gi.repository import GtkSpell
except (ImportError, ValueError):
	has_gtkspell = False
else:
	has_gtkspell = True

class Plugin(plugins.ClientPlugin):
	authors = ['Spencer McIntyre']
	title = 'Spell Check'
	description = """
	Add spell check capabilities to the message editor. This requires GtkSpell
	to be available with the correct Python GObject Introspection bindings.
	After being loaded, the language can be changed from the default of en_US
	via the context menu (available when right clicking in the text view).
	"""
	homepage = 'https://github.com/securestate/king-phisher-plugins'
	req_packages = {
		'gi.repository.GtkSpell': has_gtkspell
	}
	version = '1.1'
	def initialize(self):
		self.checker = GtkSpell.Checker()
		self.checker.set_language(self.config.get('language', 'en_US'))

		window = self.application.main_window
		mailer_tab = window.tabs['mailer']
		edit_tab = mailer_tab.tabs['edit']
		self.checker.attach(edit_tab.textview)
		return True

	def finalize(self):
		self.config['language'] = self.checker.get_language()
		self.checker.detach()
