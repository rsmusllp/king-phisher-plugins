import codecs
import os

import king_phisher.client.gui_utilities as gui_utilities
import king_phisher.client.mailer as mailer
import king_phisher.client.plugins as plugins
import king_phisher.client.widget.extras as extras

import jinja2.exceptions

try:
	from weasyprint import HTML
except (ImportError, FileNotFoundError):
	has_weasyprint = False
else:
	has_weasyprint = True

class Plugin(getattr(plugins, 'ClientPluginMailerAttachment', plugins.ClientPlugin)):
	authors = ['Jeremy Schoeneman', 'Erik Daguerre']
	classifiers = ['Plugin :: Client :: Email :: Attachment']
	title = 'Generate PDF'
	description = """
	Generates a PDF file from an html attachment that process client King Phisher Jinja variables
	allowing to embed links to your landing page so users that click the link in the PDF can be tracked
	when they visit.
	"""
	homepage = 'https://github.com/securestate/king-phisher-plugins'
	options = [
		plugins.ClientOptionPath(
			'css_stylesheet',
			'CSS stylesheet to use for HTML to PDF',
			display_name='CSS stylesheet',
			path_type='file-open'
		)
	]
	req_min_version = '1.8.0'
	req_packages = {
		'weasyprint==47': has_weasyprint
	}
	req_platforms = ('Linux',)
	version = '2.0'
	def initialize(self):
		self.add_menu_item('Tools > Create PDF Preview', self.make_preview)
		return True

	def make_preview(self, _):
		mailer_tab = self.application.main_tabs['mailer']
		config_tab = mailer_tab.tabs['config']
		config_tab.objects_save_to_config()
		input_path = self.application.config['mailer.attachment_file']
		if not (os.path.isfile(input_path) and os.access(input_path, os.R_OK)):
			gui_utilities.show_dialog_error(
				'PDF Build Error',
				self.application.get_active_window(),
				'Attachment path is invalid or is not readable.'
			)
			return

		dialog = extras.FileChooserDialog('Save Generated PDF File', self.application.get_active_window())
		response = dialog.run_quick_save('PDF Preview.pdf')
		dialog.destroy()
		if response is None:
			return

		output_path = response['target_path']
		if not self.process_attachment_file(input_path, output_path):
			return
		gui_utilities.show_dialog_info(
			'PDF Created',
			self.application.get_active_window(),
			'Successfully created the PDF file.'
		)

	def process_attachment_file(self, input_path, output_path, target=None):
		output_path, _ = os.path.splitext(output_path)
		output_path += '.pdf'
		try:
			with codecs.open(input_path, 'r', encoding='utf-8') as file_:
				msg_template = file_.read()
		except UnicodeDecodeError as error:
			gui_utilities.show_dialog_error(
				'PDF Build Error',
				self.application.get_active_window(),
				"HTML template not in UTF-8 format.\n\n{error}".format(error=error)
			)
			return

		try:
			formatted_message = mailer.render_message_template(msg_template, self.application.config, target)
		except jinja2.exceptions.TemplateSyntaxError as error:
			gui_utilities.show_dialog_error(
				'PDF Build Error',
				self.application.get_active_window(),
				"Template syntax error: {error.message} on line {error.lineno}.".format(error=error)
			)
			return
		except jinja2.exceptions.UndefinedError as error:
			gui_utilities.show_dialog_error(
				'PDF Build Error',
				self.application.get_active_window(),
				"Template undefined error: {error.message}.".format(error=error)
			)
			return
		except TypeError as error:
			gui_utilities.show_dialog_error(
				'PDF Build Error',
				self.application.get_active_window(),
				"Template type error: {0}.".format(error.args[0])
			)
			return

		css_style = self.config.get('css_stylesheet')
		if css_style:
			css_style = css_style.strip()
			if not (os.path.isfile(css_style) and os.access(css_style, os.R_OK)):
				self.logger.warning('invalid css file path: ' + css_style)
				css_style = None

		weasyprint_html = HTML(string=formatted_message, base_url=os.path.dirname(input_path))
		weasyprint_html.write_pdf(
			output_path,
			stylesheets=[css_style] if css_style else None,
			presentational_hints=True
		)
		return output_path
