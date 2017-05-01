import logging

from . import sftp_utilities

from king_phisher.client.widget import completion_providers
from king_phisher import utilities

from gi.repository import GtkSource

logger = logging.getLogger('KingPhisher.Plugins.SFTPClient')

class SFTPEditor(object):
	"""
	Handles the editor tab functions
	"""
	def __init__(self, file_path, directory, location):
		"""
		This class is used to set up the Gtk.SourceView instance to edit the file

		:param str file_contents: 
		:param str file_path: the path of the file to edit
		:param directory: the local or remote directory instance
		:param str location: the locate either remote or local
		"""
		# get editor tab objects
		if location not in ('Remote', 'Local'):
			logger.warning("location must be remote or local not {}".format(location))
			return
		self.location = location
		self.file_path = file_path
		self.file_contents = None
		self.directory = directory

		self.notebook = sftp_utilities.get_object('SFTPClient.notebook')
		self.sourceview_editor = sftp_utilities.get_object('SFTPClient.notebook.page_editor.sourceview')
		self.save_button = sftp_utilities.get_object('SFTPClient.notebook.page_editor.toolbutton_save_html_file')
		self.template_button = sftp_utilities.get_object('SFTPClient.notebook.page_editor.toolbutton_template_wiki')
		self.template_button.connect('clicked', self.signal_template_help)
		self.statusbar = sftp_utilities.get_object('SFTPClient.notebook.page_editor.statusbar')

		# set up sourceview for editing
		self.sourceview_editor.set_buffer(GtkSource.Buffer())
		self.view_completion = self.sourceview_editor.get_completion()
		self.sourceview_buffer = self.sourceview_editor.get_buffer()
		language_manager = GtkSource.LanguageManager()
		self.sourceview_buffer.set_language(language_manager.get_language('html'))
		if not self.view_completion.get_providers():
			self.view_completion.add_provider(completion_providers.HTMLComletionProvider())
			self.view_completion.add_provider(completion_providers.JinjaPageComletionProvider())
			logger.info('successfully loaded HTML and Jinja comletion providers')
		self.sourceview_buffer.connect('changed', self.signal_buff_changed)

	def signal_buff_changed(self, _):
		if self.save_button.is_sensitive():
			return
		self.save_button.set_sensitive(True)

	def load_file(self, file_contents):
		if not isinstance(file_contents, str):
			logger.info("error got file_contents type of {} should be utf-8 string".format(type(file_contents)))
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
		self.sourceview_buffer.set_highlight_syntax(True)
		self.statusbar.push(self.statusbar.get_context_id(self.location + ' File: ' + self.file_path), self.location + ' File: ' + self.file_path)
		self.notebook.set_current_page(1)
		logger.info("sftp editor set to {} file {}".format(self.location, self.file_path))

	def signal_template_help(self, _):
		utilities.open_uri('https://github.com/securestate/king-phisher/wiki/Templates#web-page-templates')


