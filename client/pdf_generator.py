import time
import os

import king_phisher.client.mailer as mailer
import king_phisher.client.plugins as plugins
import king_phisher.client.gui_utilities as gui_utilities

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

def _render_path(outfile, *joins, pathmod=os.path):
	outfile = pathmod.expandvars(outfile)
	outfile = pathmod.expanduser(outfile)
	outfile.join(outfile, *joins)
	return outfile

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
		plugins.ClientOptionString(
			'output_pdf',
			'pdf being generated',
			default='~/Attachment1.pdf',
			display_name='* Output PDF File'
		),
		plugins.ClientOptionString(
			'template_file',
			'Template file to read from',
			default='~/template.txt',
			display_name='* Template File'
		),
		plugins.ClientOptionString(
			'logo',
			'Image to include into the pdf',
			display_name='Logo / Inline Image'
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

	def signal_send_precheck(self, _):
		# file and option checks
		if not all((self.config['template_file'], self.config['output_pdf'], self.config['link_text'])):
			self.logger.debug('skipping exporting any attachments due to lack of information provided to run')
			return False
		if not os.path.isfile(self.render_path(self.config['template_file'])):
			self.logger.error('template file does not exist, specify a valid template file')
			gui_utilities.show_dialog_error(
				'File Error',
				self.application.get_active_window(),
				'Template file not found.'
			)
			return False
		self.logger.debug('pdf template file found, creating attachment')
		return True

	def make_preview(self, _):
		if not os.path.isfile(self.render_path(self.config['template_file'])):
			self.logger.error('template file does not exist, please review your options')
			gui_utilities.show_dialog_error(
				'File Error',
				self.application.get_active_window(),
				'Template file not found.'
			)
			return False

		outfile = self.render_path(self.config['output_pdf'])
		pdf_file = platypus.SimpleDocTemplate(outfile,
			pagesize=letter,
			rightMargin=72,
			leftMargin=72,
			topMargin=72,
			bottomMargin=18
		)
		url = self.application.config['mailer.webserver_url']
		pdf = self.get_template(url)
		pdf_file.multiBuild(pdf)
		self.logger.info('created, check ' + outfile)
		gui_utilities.show_dialog_info(
				'PDF Created',
				self.application.get_active_window(),
				'PDF File Created Successfully.'
			)

	def signal_send_target(self, _, target):
		outfile = self.render_path(self.config['output_pdf'])
		pdf_file = platypus.SimpleDocTemplate(outfile,
			pagesize=letter,
			rightMargin=72,
			leftMargin=72,
			topMargin=72,
			bottomMargin=18
		)
		url = self.application.config['mailer.webserver_url'] + '?uid=' + target.uid
		pdf = self.get_template(url)
		try:
			pdf_file.multiBuild(pdf)
			self.attach_pdf(outfile)
		except Exception as err:
			self.logger.error(..., exc_info=True)
		else:
			self.logger.info('pdf attachement made linking with uid: ' + target.uid)

	def get_template(self, url):
		logo_path = self.render_path(self.config['logo'])
		formatted_time = time.ctime()
		company = self.application.config['mailer.company_name']
		sender = self.application.config['mailer.source_email_alias']
		template_file = self.render_path(self.config['template_file'])
		story = []
		click_me = self.config['link_text']
		link = '<font color=blue><link href="' + str(url) + '">' + click_me + '</link></font>'
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

	def attach_pdf(self, outfile):
		self.application.config['mailer.attachment_file'] = outfile

	def signal_send_finished(self, _):
		if not os.path.isfile(self.render_path(self.config['output_pdf'])) and os.access(self.render_path(self.config['output_pdf']), os.W_OK):
			self.logger.error('no pdf file found at: ' + str(self.config['output_pdf']))
			return
		self.logger.info('deleting pdf file: ' + str(self.config['output_pdf']))
		try:
			os.remove(self.render_path(self.config['output_pdf']))
		except Exception as err:
			self.logger.debug(..., exc_info=True)
		self.application.config['mailer.attachment_file'] = None

	def render_path(self, outfile, *args, **kwargs):
		expanded_path = _render_path(outfile, *args, **kwargs)
		try:
			expanded_path = mailer.render_message_template(expanded_path, self.application.config)
		except jinja2.exceptions.TemplateSyntaxError as error:
			self.logger.error("jinja2 syntax error ({0}) in directory: {1}".format(error.message, outfile))
			self.text_insert("Jinja2 syntax error ({0}) in directory: {1}\n".format(error.message, outfile))
			return None
		except ValueError as error:
			self.logger.error("value error ({0}) in directory: {1}".format(error, outfile))
			self.text_insert("Value error ({0}) in directory: {1}\n".format(error, outfile))
			return None
		return expanded_path
