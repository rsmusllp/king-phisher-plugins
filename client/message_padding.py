import king_phisher.client.plugins as plugins

import os

PLUGIN_PATH = os.path.realpath(os.path.dirname(__file__))
STATIC_PADDING = """\
<p style=\"font-size: 0px\">It is a long established fact that a reader will be distracted by the readable content of a page when looking at its layout. \
The point of using Lorem Ipsum is that it has a more-or-less normal distribution of letters, as opposed to using 'Content here, content here', making it \
look like readable English. Many desktop publishing packages and web page editors now use Lorem Ipsum as their default model text, and a search for 'lorem \
ipsum' will uncover many web sites still in their infancy. Various versions have evolved over the years, sometimes by accident, sometimes on purpose. \
Contrary to popular belief, Lorem Ipsum is not simply random text. It has roots in a piece of classical Latin literature from 45 BC, making it over 2000 \
years old. Richard McClintock, a Latin professor at Hampden-Sydney College in Virginia, looked up one of the more obscure Latin words, consectetur, from a \
Lorem Ipsum passage, and going through the cites of the word in classical literature, discovered the undoubtable source. Lorem Ipsum comes from sections \
1.10.32 and 1.10.33 of 'de Finibus Bonorum et Malorum' (The Extremes of Good and Evil) by Cicero, written in 45 BC. This book is a treatise on the theory \
of ethics, very popular during the Renaissance. The first line of Lorem Ipsum, 'Lorem ipsum dolor sit amet..', comes from a line in section 1.10.32. The \
standard chunk of Lorem Ipsum used since the 1500s is reproduced below for those interested. Sections 1.10.32 and 1.10.33 from 'de Finibus Bonorum et \
Malorum' by Cicero are also reproduced in their exact original form, accompanied by English versions from the 1914 translation by H. Rackham. The \
point of using Lorem Ipsum is that it has a more-or-less normal distribution of letters, as opposed to using 'Content here, content here', making it \
look like readable English. Many desktop publishing packages and web page editors now use Lorem Ipsum as their default model text, and a search for 'lorem \
ipsum' will uncover many web sites still in their infancy. Various versions have evolved over the years, sometimes by accident, sometimes on purpose. \
Contrary to popular belief, Lorem Ipsum is not simply random text. It has roots in a piece of classical Latin literature from 45 BC, making it over 2000 \
years old. Richard McClintock, a Latin professor at Hampden-Sydney College in Virginia, looked up one of the more obscure Latin words, consectetur, from a \
Lorem Ipsum passage, and going through the cites of the word in classical literature, discovered the undoubtable source. Lorem Ipsum comes from sections \
1.10.32 and 1.10.33 of 'de Finibus Bonorum et Malorum' (The Extremes of Good and Evil) by Cicero, written in 45 BC. This book is a treatise on the theory \
of ethics, very popular during the Renaissance. The first line of Lorem Ipsum, 'Lorem ipsum dolor sit amet..', comes from a line in section 1.10.32. The \
standard chunk of Lorem Ipsum used since the 1500s is reproduced below for those interested. Sections 1.10.32 and 1.10.33 from 'de Finibus Bonorum et \
Malorum' by Cicero are also reproduced in their exact original form, accompanied by English versions from the 1914 translation by H. Rackham. \
The point of using Lorem Ipsum is that it has a more-or-less normal distribution of letters, as opposed to using 'Content here, content here', making it \
look like readable English. Many desktop publishing packages and web page editors now use Lorem Ipsum as their default model text, and a search for 'lorem \
ipsum' will uncover many web sites still in their infancy. Various versions have evolved over the years, sometimes by accident, sometimes on purpose. \
Contrary to popular belief, Lorem Ipsum is not simply random text. It has roots in a piece of classical Latin literature from 45 BC, making it over 2000 \
years old. Richard McClintock, a Latin professor at Hampden-Sydney College in Virginia, looked up one of the more obscure Latin words, consectetur, from a \
Lorem Ipsum passage, and going through the cites of the word in classical literature, discovered the undoubtable source. Lorem Ipsum comes from sections \
1.10.32 and 1.10.33 of 'de Finibus Bonorum et Malorum' (The Extremes of Good and Evil) by Cicero, written in 45 BC. This book is a treatise on the theory \
of ethics, very popular during the Renaissance. The first line of Lorem Ipsum, 'Lorem ipsum dolor sit amet..', comes from a line in section 1.10.32. The \
standard chunk of Lorem Ipsum used since the 1500s is reproduced below for those interested. Sections 1.10.32 and 1.10.33 from 'de Finibus Bonorum et \
Malorum' by Cicero are also reproduced in their exact original form, accompanied by English versions from the 1914 translation by H. Rackham.</p>\
"""

try:
	import markovify
except ImportError:
	has_markovify = False
else:
	has_markovify = True

class Plugin(plugins.ClientPlugin):
	authors = ['Spencer McIntyre', 'Mike Stringer']
	classifiers = ['Plugin :: Client :: Email :: Spam Evasion']
	title = 'Message Padding'
	description = """
	Add and modify custom HTML messages from a file to reduce Spam Assassin
	scores. This plugin interacts with the message content to append a long
	series of randomly generated sentences to meet the ideal image-text ratio.
	"""
	homepage = 'https://github.com/securestate/king-phisher-plugins'
	options = [
		plugins.ClientOptionString(
			'corpus',
			description='Text file containing text to generate dynamic padding',
			default=os.path.join(PLUGIN_PATH, 'corpus.txt'),
			display_name='Corpus File'
		),
		plugins.ClientOptionBoolean(
			'dynamic_padding',
			description='Sets whether dynamically generated or static padding is appended to the messaged',
			default=True
		)
	]
	req_min_version = '1.10.0'
	version = '1.0'
	req_packages = {
		'markovify': has_markovify
	}
	def initialize(self):
		mailer_tab = self.application.main_tabs['mailer']
		self.signal_connect('message-create', self.signal_message_create, gobject=mailer_tab)
		if os.path.isfile(os.path.realpath(self.config['corpus'])):
			self.corpus = os.path.realpath(self.config['corpus'])
		else:
			self.corpus = None
		self.logger.debug('corpus file: ' + repr(self.corpus))
		if self.corpus:
			self.dynamic = self.config['dynamic_padding']
		else:
			if self.config['dynamic_padding']:
				self.logger.warning('the corpus file is unavailable, ignoring the dynamic padding setting')
			self.dynamic = False
		return True

	def signal_message_create(self, mailer_tab, target, message):
		for part in message.walk():
			if not part.get_content_type().startswith('text/html'):
				continue
			payload_string = part.payload_string
			tag = '</html>'
			if tag not in payload_string:
				self.logger.warning('can not find ' + tag + ' tag to anchor the message padding')
				continue
			part.payload_string = payload_string.replace(tag, self.make_padding() + tag)

	def make_padding(self):
		if self.dynamic:
			f = open(self.corpus, 'r')
			text = markovify.Text(f)
			self.logger.info('generating dynamic padding from corpus')
			pad = '<p style="font-size: 0px">'
			for i in range(1, 50):
				temp = text.make_sentence()
				if temp is not None:
					pad += ' ' + temp
					if i % 5 == 0:
						pad +=' </br>'
				else:
					pad += ' </br>'
			pad += ' </p>'
			self.logger.info('dynamic padding generated successfully')
			f.close()
		else:
			self.logger.warning('message created using static padding')
			pad = STATIC_PADDING
		return pad
