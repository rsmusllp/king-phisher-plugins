import logging

from . import sftp_utilities

from king_phisher.client.widget import completion_providers
from king_phisher import utilities

from gi.repository import GtkSource
from gi.repository import Pango

logger = logging.getLogger('KingPhisher.Plugins.SFTPClient')

class SFTPEditor(object):
	"""
	Handles the editor tab functions
	"""
	def __init__(self, application, file_path, directory):
		"""
		This class is used to set up the Gtk.SourceView instance to edit the file

		:param application: The main client application instance.
		:type application: :py:class:`Gtk.Application`
		:param str file_path: the path of the file to edit
		:param directory: the local or remote directory instance
		"""
		self.application = application
		# get editor tab objects
		self.file_location = directory.location
		self.file_path = file_path
		self.file_contents = None
		self.directory = directory

		config = self.application.config
		self.sourceview_editor = sftp_utilities.get_object('SFTPClient.notebook.page_editor.sourceview')
		self.save_button = sftp_utilities.get_object('SFTPClient.notebook.page_editor.toolbutton_save_html_file')
		self.template_button = sftp_utilities.get_object('SFTPClient.notebook.page_editor.toolbutton_template_wiki')
		self.template_button.connect('clicked', self.signal_template_help)
		self.statusbar = sftp_utilities.get_object('SFTPClient.notebook.page_editor.statusbar')

		# set up sourceview for editing
		self.sourceview_buffer = GtkSource.Buffer()
		self.sourceview_buffer.connect('changed', self.signal_buff_changed)
		self.sourceview_editor.set_buffer(self.sourceview_buffer)
		self.sourceview_editor.modify_font(Pango.FontDescription(config['text_font']))
		language_manager = GtkSource.LanguageManager()
		self.sourceview_buffer.set_language(language_manager.get_language('html'))
		self.sourceview_buffer.set_highlight_syntax(True)
		self.sourceview_editor.set_property('highlight-current-line', config.get('text_source.highlight_line', True))
		self.sourceview_editor.set_property('indent-width', config.get('text_source.tab_width', 4))
		self.sourceview_editor.set_property('insert-spaces-instead-of-tabs', not config.get('text_source.hardtabs', False))
		self.sourceview_editor.set_property('tab-width', config.get('text_source.tab_width', 4))

		scheme_manager = GtkSource.StyleSchemeManager()
		style_scheme_name = config.get('text_source.theme', 'cobalt')
		style_scheme = scheme_manager.get_scheme(style_scheme_name)
		if style_scheme:
			self.sourceview_buffer.set_style_scheme(style_scheme)
		else:
			logger.error("invalid GTK source theme: '{0}'".format(style_scheme_name))

		self.view_completion = self.sourceview_editor.get_completion()
		self.view_completion.set_property('accelerators', 0)
		self.view_completion.set_property('auto-complete-delay', 250)
		self.view_completion.set_property('show-icons', False)

		if not self.view_completion.get_providers():
			self.view_completion.add_provider(completion_providers.HTMLComletionProvider())
			self.view_completion.add_provider(completion_providers.JinjaPageComletionProvider())
			logger.info('successfully loaded HTML and Jinja comletion providers')

	def signal_buff_changed(self, _):
		if self.save_button.is_sensitive():
			return
		self.save_button.set_sensitive(True)

	def load_file(self, file_contents):
		if not isinstance(file_contents, str):
			logger.info("received file_contents type of {} should be utf-8 string".format(type(file_contents)))
			file_contents = file_contents.decode('utf-8')
		self.sourceview_buffer.begin_not_undoable_action()
		self.sourceview_buffer.set_text(file_contents)
		self.file_contents = self.sourceview_buffer.get_text(
			self.sourceview_buffer.get_start_iter(),
			self.sourceview_buffer.get_end_iter(),
			False
		)
		self.sourceview_buffer.end_not_undoable_action()
		self.save_button.set_sensitive(False)
		self.statusbar.push(self.statusbar.get_context_id(self.file_location + ' file: ' + self.file_path), self.file_location + ' file: ' + self.file_path)
		logger.info("sftp editor set to {} file {}".format(self.file_location, self.file_path))

	def signal_template_help(self, _):
		utilities.open_uri('https://github.com/securestate/king-phisher/wiki/Templates#web-page-templates')
