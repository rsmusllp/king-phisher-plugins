#!/usr/bin/python3

import sys
import time
import os

from reportlab.lib.enums import TA_JUSTIFY
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab import platypus
from  reportlab.lib.styles import ParagraphStyle as PS

import king_phisher.client.mailer as mailer
import king_phisher.client.plugins as plugins

import jinja2.exceptions

def _expand_path(outfile, *joins, pathmod=os.path):
        outfile = pathmod.expandvars(outfile)
        outfile = pathmod.expanduser(outfile)
        outfile.join(outfile, *joins)
        return outfile

class Plugin(plugins.ClientPlugin):
	authors = ['Jeremy Schoeneman']
	title = 'Generate PDF and Send'
	description = """
	Generates a pdf with a link which includes a url with message_id required to track
	individual visits to a website.
	"""
	homepage = 'https://github.com/securestate/king-phisher-plugins'
	options = [
		plugins.ClientOptionString(
			'output_pdf',
			'PDF being generated',
			default='$HOME/Attachment1.pdf',
			display_name='PDF File'
		),
		
		plugins.ClientOptionString(
			'template_file',
			'Template file to read from',
			default='$HOME/template.txt',
			display_name='Template File'
		),

		plugins.ClientOptionString(
			'logo',
			'Image to include into the pdf',
			display_name="Logo Image to Include"
		),

		plugins.ClientOptionString(
			'link_text',
			'Text for inserted link',
			default='Click here to accept',
			display_name="Link Text"
		)
	]
	req_min_version = '1.6'
	version = '1.1'

	def initialize(self):
		mailer_tab = self.application.main_tabs['mailer']
		self.text_insert = mailer_tab.tabs['send_messages'].text_insert
		self.signal_connect('send-precheck', self.signal_send_precheck, gobject=mailer_tab)
		self.signal_connect('send-target', self.signal_send_target, gobject=mailer_tab)
		self.signal_connect('send-finished', self.signal_send_finished, gobject=mailer_tab)
		return True

	def signal_send_precheck(self, _):
		if not os.path.isfile(self.config['template_file']):
			self.logger.error('No template file found' )
			return
		else:
			self.logger.info('Template File found, exporting PDF File')
			return True

	def signal_send_target(self, _, target):
		outfile = self.expand_path(self.config['output_pdf'])
		pdf_file = SimpleDocTemplate(outfile, pagesize=letter,
	                        rightMargin=72,leftMargin=72,
	                        topMargin=72,bottomMargin=18)
		url = self.application.config['mailer.webserver_url'] + '?uid=' + str(target.uid)

		pdf = self.get_template(url)
		pdf_file.multiBuild(pdf)
		self.logger.info('Attachment made for uid: ' + str(target.uid) )
		self.attach_pdf(outfile)

	def get_template(self, url):
		# Variables
		logo = self.config['logo']
		formatted_time = time.ctime()
		company = self.application.config['mailer.company_name']
		sender = self.application.config['mailer.source_email_alias']

		Story=[]
		
		#Link Building
		click_me = self.config['link_text']
		link = '<font color=blue><link href="' + str(url) + '">' + click_me + '</link></font>'
		if self.config['logo']:
			im = Image(logo,2*inch, 1*inch)
			Story.append(im)

		styles=getSampleStyleSheet()
		styles.add(PS(name='Justify', alignment=TA_JUSTIFY))
		
		ptext = '<font size=10>%s</font>' % formatted_time
		
		Story.append(Spacer(1, 12))
		
		# Create return address
		Story.append(Paragraph(ptext, styles["Normal"]))        
		Story.append(Spacer(1, 12))
		
		#input from template file	
		with open(self.config['template_file'], 'r') as t:
			for line in t:
				Story.append(Paragraph(line, styles["Normal"]))
	
		# add link
		Story.append(Spacer(1, 8))
		Story.append(platypus.Paragraph(link, styles["Justify"]))
		Story.append(Spacer(1, 12))
		ptext = '<font size=10>Sincerely,</font>'
		Story.append(Paragraph(ptext, styles["Normal"]))
		
		Story.append(Spacer(1, 12))
		ptext = '<font size=10>'+ sender + '</font>'
		Story.append(Paragraph(ptext, styles["Normal"]))
		return Story

	def attach_pdf(self, outfile):
		self.application.config['mailer.attachment_file'] = outfile

	def signal_send_finished(self, _):
		if not os.path.isfile(self.config['output_pdf']):
			return
		else:
			self.logger.info('Deleting Created PDF: ' + str(self.config['output_pdf']) )
			os.remove(self.config['output_pdf'])
		self.application.config['mailer.attachment_file'] = None

	def expand_path(self, outfile, *args, **kwargs):
		expanded_path = _expand_path(outfile, *args, **kwargs)
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
