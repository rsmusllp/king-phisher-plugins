import os
import logging

from . import sftp_utilities

from king_phisher.client.widget import completion_providers
from king_phisher import utilities

from gi.repository import Gtk
from gi.repository import GtkSource

logger = logging.getLogger('KingPhisher.Plugins.SFTPClient.editor')

class SftpEditor(object):
	"""
	Handles the editor tab functions
	"""
	def __init__(self, file_contents, file_path, location):
		"""
		
		:param file_contents: the contents of the file to be edited
		:param str location: local or remote connection
		"""
		# get editor tab objects
		if not isinstance(file_contents, str):
			print("error got file_contents type of {}".format(type(file_contents)))
			file_contents = file_contents.decode()
		self.location = location
		self.file_path = file_path
		self.file_contents = file_contents

		self.notebook = sftp_utilities.get_object('SFTPClient.notebook')
		self.sourceview_editor = sftp_utilities.get_object('SFTPClient.notebook.page_editor.sourceview')
		self.save_button = sftp_utilities.get_object('SFTPClient.notebook.page_editor.toolbutton_save_html_file')
		self.template_button = sftp_utilities.get_object('SFTPClient.notebook.page_editor.toolbutton_template_wiki')
		self.template_button.connect('clicked', self.signal_template_help)

		# set up sourceview for editing
		self.sourceview_editor.set_buffer(GtkSource.Buffer())
		self.view_completion = self.sourceview_editor.get_completion()
		self.sourceview_buffer = self.sourceview_editor.get_buffer()
		language_manager = GtkSource.LanguageManager()
		self.sourceview_buffer.set_language(language_manager.get_language('html'))
		self.view_completion.add_provider(completion_providers.HTMLComletionProvider())
		self.view_completion.add_provider(completion_providers.JinjaPageComletionProvider())

		self._loadfile()

	def _loadfile(self):
		self.sourceview_buffer.begin_not_undoable_action()
		self.sourceview_buffer.set_text(self.file_contents)
		self.file_contents = self.sourceview_buffer.get_text(
			self.sourceview_buffer.get_start_iter(),
			self.sourceview_buffer.get_end_iter(),
			False
		)
		self.sourceview_buffer.end_not_undoable_action()
		self.save_button.set_sensitive(True)
		self.sourceview_buffer.set_highlight_syntax(True)
		self.notebook.set_current_page(1)

	def signal_template_help(self, _):
		utilities.open_uri('https://github.com/securestate/king-phisher/wiki/Templates#web-page-templates')


