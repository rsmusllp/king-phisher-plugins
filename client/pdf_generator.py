import os
import time
import xml.sax.saxutils as saxutils

import king_phisher.client.gui_utilities as gui_utilities
import king_phisher.client.mailer as mailer
import king_phisher.client.plugins as plugins
import king_phisher.client.widget.extras as extras

import jinja2.exceptions

try:
	from reportlab import platypus
	from reportlab.lib import styles
	from reportlab.lib.enums import TA_JUSTIFY
	from reportlab.lib.pagesizes import letter
	from reportlab.lib.units import inch
except ImportError:
	has_reportlab = False
else:
	has_reportlab = True

class Plugin(getattr(plugins, 'ClientPluginMailerAttachment', plugins.ClientPlugin)):
	authors = ['Jeremy Schoeneman']
	title = 'Generate PDF'
	description = """
	Generates a PDF file with a link which includes the campaign URL with the
	individual message_id required to track individual visits to a website.
	Visit https://github.com/y4utj4/pdf_generator for example template files to
	use with this plugin.
	"""
	homepage = 'https://github.com/securestate/king-phisher-plugins'
	options = [
		plugins.ClientOptionPath(
			'logo',
			'Image to include into the pdf',
			display_name='Logo / Inline Image',
			path_type='file-open'
		),
		plugins.ClientOptionString(
			'link_text',
			'Text for inserted link',
			default='Click here to accept',
			display_name='Link Text'
		)
	]
	req_min_version = '1.8.0b0'
	req_packages = {
		'reportlab': has_reportlab
	}
	version = '1.1'
	def initialize(self):
		mailer_tab = self.application.main_tabs['mailer']
		self.add_menu_item('Tools > Create PDF Preview', self.make_preview)
		return True

	def make_preview(self, _):
		input_path = self.application.config['mailer.attachment_file']
		if not os.path.isfile(input_path) and os.access(input_path, os.R_OK):
			gui_utilities.show_dialog_error(
				'PDF Build Error',
				self.application.get_active_window(),
				'An invalid attachment file is specified.'
			)
			return

		dialog = extras.FileChooserDialog('Save Generated PDF File', self.application.get_active_window())
		response = dialog.run_quick_save('preview.pdf')
		dialog.destroy()
		if response is None:
			return

		output_path = response['target_path']
		if not self.process_attachment_file(input_path, output_path):
			gui_utilities.show_dialog_error(
				'PDF Build Error',
				self.application.get_active_window(),
				'Failed to create the PDF file.'
			)
			return
		gui_utilities.show_dialog_info(
			'PDF Created',
			self.application.get_active_window(),
			'Successfully created the PDF file.'
		)

	def process_attachment_file(self, input_path, output_path, target=None):
		output_path, _ = os.path.splitext(output_path)
		output_path += '.pdf'

		pdf_file = platypus.SimpleDocTemplate(
			output_path,
			pagesize=letter,
			rightMargin=72,
			leftMargin=72,
			topMargin=72,
			bottomMargin=18
		)

		url = self.application.config['mailer.webserver_url']
		if target is not None:
			url += '?uid=' + target.uid

		try:
			pdf_template = self.get_template(input_path, url)
			pdf_file.multiBuild(pdf_template)
		except Exception as err:
			self.logger.error('failed to build the pdf document', exc_info=True)
			return
		self.logger.info('wrote pdf file to: ' + output_path + ('' if target is None else ' with uid: ' + target.uid))
		return output_path

	def get_template(self, template_file, url):
		formatted_time = time.ctime()
		company = self.application.config['mailer.company_name']
		sender = self.application.config['mailer.source_email_alias']

		story = []
		click_me = saxutils.escape(self.config['link_text'])
		link = '<font color=blue><link href="' + url + '">' + click_me + '</link></font>'

		logo_path = self.config['logo']
		if logo_path:
			img = platypus.Image(logo_path, 2 * inch, inch)
			story.append(img)

		style_sheet = styles.getSampleStyleSheet()
		style_sheet.add(styles.ParagraphStyle(name='Justify', alignment=TA_JUSTIFY))
		ptext = '<font size=10>' + formatted_time + '</font>'
		story.append(platypus.Spacer(1, 12))
		story.append(platypus.Paragraph(ptext, style_sheet['Normal']))
		story.append(platypus.Spacer(1, 12))
		with open(template_file, 'r') as file_h:
			for line in file_h:
				story.append(platypus.Paragraph(line, style_sheet['Normal']))
		story.append(platypus.Spacer(1, 8))
		story.append(platypus.Paragraph(link, style_sheet['Justify']))
		story.append(platypus.Spacer(1, 12))
		ptext = '<font size=10>Sincerely,</font>'
		story.append(platypus.Paragraph(ptext, style_sheet['Normal']))
		story.append(platypus.Spacer(1, 12))
		ptext = '<font size=10>' + sender + '</font>'
		story.append(platypus.Paragraph(ptext, style_sheet['Normal']))
		story.append(platypus.Spacer(1, 12))
		ptext = '<font size=10>' + company + '</font>'
		story.append(platypus.Paragraph(ptext, style_sheet['Normal']))
		return story
