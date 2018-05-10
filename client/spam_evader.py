import king_phisher.version as version
import king_phisher.client.plugins as plugins

import os

PLUGIN_PATH = os.path.realpath(os.path.dirname(__file__))
STATIC_PADDING = "<p style=\"font-size: 0px\">It is a long established fact that a reader will be distracted by the readable content of a page when looking at its layout. " \
	"The point of using Lorem Ipsum is that it has a more-or-less normal distribution of letters, as opposed to using 'Content here, content here', making it " \
	"look like readable English. Many desktop publishing packages and web page editors now use Lorem Ipsum as their default model text, and a search for 'lorem" \
	" ipsum' will uncover many web sites still in their infancy. Various versions have evolved over the years, sometimes by accident, sometimes on purpose. " \
	"Contrary to popular belief, Lorem Ipsum is not simply random text. It has roots in a piece of classical Latin literature from 45 BC, making it over 2000 " \
	"years old. Richard McClintock, a Latin professor at Hampden-Sydney College in Virginia, looked up one of the more obscure Latin words, consectetur, from a" \
	" Lorem Ipsum passage, and going through the cites of the word in classical literature, discovered the undoubtable source. Lorem Ipsum comes from sections " \
	"1.10.32 and 1.10.33 of 'de Finibus Bonorum et Malorum' (The Extremes of Good and Evil) by Cicero, written in 45 BC. This book is a treatise on the theory " \
	"of ethics, very popular during the Renaissance. The first line of Lorem Ipsum, 'Lorem ipsum dolor sit amet..', comes from a line in section 1.10.32. The " \
	"standard chunk of Lorem Ipsum used since the 1500s is reproduced below for those interested. Sections 1.10.32 and 1.10.33 from 'de Finibus Bonorum et " \
	"Malorum' by Cicero are also reproduced in their exact original form, accompanied by English versions from the 1914 translation by H. Rackham. The " \
	"point of using Lorem Ipsum is that it has a more-or-less normal distribution of letters, as opposed to using 'Content here, content here', making it " \
	"look like readable English. Many desktop publishing packages and web page editors now use Lorem Ipsum as their default model text, and a search for 'lorem" \
	" ipsum' will uncover many web sites still in their infancy. Various versions have evolved over the years, sometimes by accident, sometimes on purpose. " \
	"Contrary to popular belief, Lorem Ipsum is not simply random text. It has roots in a piece of classical Latin literature from 45 BC, making it over 2000 " \
	"years old. Richard McClintock, a Latin professor at Hampden-Sydney College in Virginia, looked up one of the more obscure Latin words, consectetur, from a" \
	" Lorem Ipsum passage, and going through the cites of the word in classical literature, discovered the undoubtable source. Lorem Ipsum comes from sections " \
	"1.10.32 and 1.10.33 of 'de Finibus Bonorum et Malorum' (The Extremes of Good and Evil) by Cicero, written in 45 BC. This book is a treatise on the theory " \
	"of ethics, very popular during the Renaissance. The first line of Lorem Ipsum, 'Lorem ipsum dolor sit amet..', comes from a line in section 1.10.32. The " \
	"standard chunk of Lorem Ipsum used since the 1500s is reproduced below for those interested. Sections 1.10.32 and 1.10.33 from 'de Finibus Bonorum et " \
	"Malorum' by Cicero are also reproduced in their exact original form, accompanied by English versions from the 1914 translation by H. Rackham." \
	"The point of using Lorem Ipsum is that it has a more-or-less normal distribution of letters, as opposed to using 'Content here, content here', making it " \
	"look like readable English. Many desktop publishing packages and web page editors now use Lorem Ipsum as their default model text, and a search for 'lorem" \
	" ipsum' will uncover many web sites still in their infancy. Various versions have evolved over the years, sometimes by accident, sometimes on purpose. " \
	"Contrary to popular belief, Lorem Ipsum is not simply random text. It has roots in a piece of classical Latin literature from 45 BC, making it over 2000 " \
	"years old. Richard McClintock, a Latin professor at Hampden-Sydney College in Virginia, looked up one of the more obscure Latin words, consectetur, from a" \
	" Lorem Ipsum passage, and going through the cites of the word in classical literature, discovered the undoubtable source. Lorem Ipsum comes from sections " \
	"1.10.32 and 1.10.33 of 'de Finibus Bonorum et Malorum' (The Extremes of Good and Evil) by Cicero, written in 45 BC. This book is a treatise on the theory " \
	"of ethics, very popular during the Renaissance. The first line of Lorem Ipsum, 'Lorem ipsum dolor sit amet..', comes from a line in section 1.10.32. The " \
	"standard chunk of Lorem Ipsum used since the 1500s is reproduced below for those interested. Sections 1.10.32 and 1.10.33 from 'de Finibus Bonorum et " \
	"Malorum' by Cicero are also reproduced in their exact original form, accompanied by English versions from the 1914 translation by H. Rackham.</p>"

try:
	import markovify
except ImportError:
	has_markov = False
else:
	has_markov = True

class Plugin(plugins.ClientPlugin):
	authors = ['Spencer McIntyre', 'Mike Stringer']
	title = 'Spam Evader'
	description = """
	Add and modify custom HTML messages from a file to reduce Spam Assassin
	scores. This plugin interacts with the message content to append a long
	series of randomly generated sentences to meet the ideal image-text ratio.
	"""
	homepage = 'https://github.com/securestate/king-phisher-plugins'
	options = [
		plugins.ClientOptionString(
			'corpus',
			description='text file containing text to generate dynamic padding',
			default=os.path.join(PLUGIN_PATH, 'corpus.txt'),
			display_name='Corpus File'
		),
		plugins.ClientOptionString(
			'dynamic_padding',
			description='Sets whether dynamically generated or static padding is appended to the messaged',
			default=True
		)
	]
	req_min_version = '1.10.0b3'
	version = '1.0'
	req_packages = {
		'python3-markovify': has_markov
	}

	def initialize(self):
		mailer_tab = self.application.main_tabs['mailer']
		self.signal_connect('message-create', self.signal_message_create, gobject=mailer_tab)
		if os.path.isfile(os.path.realpath(self.config['corpus'])):
			self.corpus = os.path.realpath(self.config['corpus'])
		else:
			self.corpus = False
		self.logger.debug("Spam Evader: Corpus File = " + self.corpus)
		if self.corpus and has_markov:
			self.dynamic = self.config['dynamic_padding']
		else:
			self.dynamic = False
		return True

	def signal_message_create(self, mailer_tab, target, message):
		payload = [part if part.get_content_type().startswith('text/html') else '' for part in message.walk()]
		padding = self.make_padding()
		payload[-1].payload_string = payload[-1].payload_string.replace('</body>', padding + '</body>')
		self.logger.debug("Message payload added:  " + payload[-1].payload_string)

	def make_padding(self):
		if self.dynamic:
			f = open(self.corpus, 'r')
			text = markovify.Text(f)
			self.logger.info("Spam Evader: Generating dynamic padding from corpus...")
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
			self.logger.info("Spam Evader: Dynamic Padding Generated Successfully")
			f.close()
		else:
			self.logger.warning("Spam Evader: Message created using static padding!")
			pad = STATIC_PADDING

		self.logger.debug("Message Padding: \n" + pad)
		return pad
