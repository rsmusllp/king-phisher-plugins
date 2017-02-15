import os
import time
import xml.sax.saxutils as saxutils

import king_phisher.client.gui_utilities as gui_utilities
import king_phisher.client.mailer as mailer
import king_phisher.client.plugins as plugins

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

class Plugin(plugins.ClientPlugin):
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
			'output_pdf',
			'pdf being generated',
			default='~/Attachment1.pdf',
			display_name='* Output PDF File',
			path_type='file-save'
		),
		plugins.ClientOptionPath(
			'template_file',
			'Template file to read from',
			default='~/template.txt',
			display_name='* Template File',
			path_type='file-open'
		),
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
	req_min_version = '1.7.0b1'
	req_packages = {
		'reportlab': has_reportlab
	}
	def initialize(self):
		mailer_tab = self.application.main_tabs['mailer']
		self.text_insert = mailer_tab.tabs['send_messages'].text_insert
		self.add_menu_item('Tools > Create PDF Preview', self.make_preview)
		self.signal_connect('send-precheck', self.signal_send_precheck, gobject=mailer_tab)
		self.signal_connect('send-target', self.signal_send_target, gobject=mailer_tab)
		self.signal_connect('send-finished', self.signal_send_finished, gobject=mailer_tab)
		return True

	def attach_pdf(self, outfile):
		self.application.config['mailer.attachment_file'] = outfile

	def missing_options(self):
		# return true if a required option is missing or otherwise invalid
		if not all((self.config['template_file'], self.config['output_pdf'], self.config['link_text'])):
			self.logger.warning('options required to generate a pdf are missing')
			gui_utilities.show_dialog_error(
				'Configuration Error',
				self.application.get_active_window(),
				'One or more of the options required to generate a PDF file are invalid.'
			)
			return True
		template_file = self.config['template_file']
		if not os.access(template_file, os.R_OK):
			self.logger.warning('can not access pdf template file: ' + template_file)
			gui_utilities.show_dialog_error(
				'Configuration Error',
				self.application.get_active_window(),
				'Can not access the PDF template file.'
			)
			return True
		return False

	def make_preview(self, _):
		if self.missing_options():
			return False
		if not self.build_pdf():
			gui_utilities.show_dialog_info(
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

	def build_pdf(self, target=None):
		output_pdf = self.config['output_pdf']
		pdf_file = platypus.SimpleDocTemplate(output_pdf,
			pagesize=letter,
			rightMargin=72,
			leftMargin=72,
			topMargin=72,
			bottomMargin=18
		)
		url = self.application.config['mailer.webserver_url']
		if target is not None:
			url += '?uid=' + target.uid
		pdf_template = self.get_template(url)
		try:
			pdf_file.multiBuild(pdf_template)
		except Exception as err:
			self.logger.error('failed to build the pdf document', exc_info=True)
			return False
		self.logger.info('wrote pdf file to: ' + output_pdf + ('' if target is None else ' with uid: ' + target.uid))
		return True

	def get_template(self, url):
		formatted_time = time.ctime()
		company = self.application.config['mailer.company_name']
		sender = self.application.config['mailer.source_email_alias']
		template_file = self.config['template_file']

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

	def signal_send_precheck(self, _):
		if self.missing_options():
			self.text_insert('One or more of the options required to generate a PDF file are invalid.\n')
			return False
		return True

	def signal_send_target(self, _, target):
		if not self.build_pdf(target):
			raise RuntimeError('failed to build the target\'s pdf file')
		self.attach_pdf(self.config['output_pdf'])

	def signal_send_finished(self, _):
		output_pdf = self.config['output_pdf']
		if not os.access(output_pdf, os.W_OK):
			self.logger.error('no pdf file found at: ' + output_pdf)
			return
		self.logger.info('deleting pdf file: ' + output_pdf)
		os.remove(output_pdf)
		self.application.config['mailer.attachment_file'] = None
