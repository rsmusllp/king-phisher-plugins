import argparse
import collections

import king_phisher.constants as constants
import king_phisher.spf as spf
import king_phisher.client.mailer as mailer
import king_phisher.client.plugins as plugins
import king_phisher.client.gui_utilities as gui_utilities

import dns.rdtypes.ANY.TXT
import dns.resolver

TAGS = {
	'adkim': 'r',
	'aspf': 'r',
	'fo': '0',
	'p': None,
	'pct': '100',
	'rf': 'afrf',
	'ri': '86400',
	'rua': None,
	'ruf': None,
	'sp': None,
	'v': None
}
"""
A dictionary of all tags defined in RFC-7489 with their default value as a
string, or None if no default value is specified.
"""

class DMARCError(Exception):
	def __init__(self, message):
		self.message = message

	def __repr__(self):
		return "<{0} message='{1}' >".format(self.__class__.__name__, self.message)

class DMARCNoRecordError(DMARCError):
	pass

class DMARCParseError(DMARCError):
	def __init__(self, message, tag=None):
		self.message = message
		self.tag = tag

class DMARCPolicy(object):
	def __init__(self, record):
		record = record.strip()
		self.record = record
		self.tags = collections.OrderedDict()
		record = record.split(';')
		# the tag specification is defined in the DKIM spec (RFC 6376) https://tools.ietf.org/html/rfc6376#section-3.2
		for token in record:
			token = token.strip()
			if not token:
				continue
			if not '=' in token:
				raise DMARCParseError('can not separate record token: ' + token)
			tag, value = token.split('=', 1)
			if tag not in TAGS:
				# ignore unknown tags per https://tools.ietf.org/html/rfc7489#section-6.3
				continue
			self.tags[tag.strip()] = value.strip()
		if 'p' in self.tags and self.tags['p'] not in ('none', 'quarantine', 'reject'):
			raise DMARCParseError("invalid dmarc record (invalid policy: {0})".format(self.tags['p']), tag='p')
		if self.version is None:
			raise DMARCParseError('invalid dmarc record (missing version tag)', tag='v')
		if self.version != 'DMARC1':
			raise DMARCParseError("invalid dmarc record (invalid version value: {0})".format(self.version), tag='v')

	def __repr__(self):
		return "<{0} v={1} >".format(self.__class__.__name__, self.version)

	def __str__(self):
		return self.record

	@classmethod
	def from_domain(cls, domain):
		if not domain.startswith('_dmarc.'):
			domain = '_dmarc.' + domain
		try:
			answers = dns.resolver.query(domain, 'TXT')
		except dns.exception.DNSException:
			raise DMARCNoRecordError("DNS resolution error for: {0} TXT".format(domain))
		answers = list(answer for answer in answers if isinstance(answer, dns.rdtypes.ANY.TXT.TXT))

		answers = [answer for answer in answers if answer.strings[0].decode('utf-8').startswith('v=DMARC')]
		if len(answers) == 0:
			raise DMARCParseError('failed to parse dmarc record for domain: ' + domain)
		record = ''.join([part.decode('utf-8') for part in answers[0].strings])
		return cls(record)

	def get(self, tag):
		if not tag in TAGS:
			raise KeyError(tag)
		return self.tags.get(tag, TAGS[tag])

	@property
	def policy(self):
		return self.tags.get('p')

	@property
	def version(self):
		return self.tags.get('v')

class Plugin(plugins.ClientPlugin):
	authors = ['Spencer McIntyre']
	classifiers = [
		'Plugin :: Client :: Email :: Spam Evasion',
		'Script :: CLI'
	]
	title = 'DMARC Check'
	description = """
	This plugin adds another safety check to the message precheck routines to
	verify that if DMARC exists the message will not be quarentined or rejected.
	If no DMARC policy is present, the policy is set to none or the percentage
	is set to 0, the message sending operation will proceed.
	"""
	homepage = 'https://github.com/securestate/king-phisher-plugins'
	reference_urls = ['https://dmarc.org/overview/']
	req_min_version = '1.5.0'
	version = '1.1'
	def initialize(self):
		self.signal_connect('send-precheck', self.signal_send_precheck, gobject=self.application.main_tabs['mailer'])
		return True

	def signal_send_precheck(self, mailer_tab):
		test_ip = mailer.guess_smtp_server_address(
			self.application.config['smtp_server'],
			(self.application.config['ssh_server'] if self.application.config['smtp_ssh_enable'] else None)
		)
		if not test_ip:
			self.logger.info('skipping dmarc policy check because the smtp server address could not be resolved')
			return True
		test_sender, test_domain = self.application.config['mailer.source_email_smtp'].split('@')
		self.logger.debug('checking the dmarc policy for domain: ' + test_domain)
		text_insert = mailer_tab.tabs['send_messages'].text_insert

		text_insert("Checking the DMARC policy of target domain '{0}'... ".format(test_domain))
		try:
			spf_result = spf.check_host(test_ip, test_domain, sender=test_sender)
		except spf.SPFError as error:
			text_insert("done, encountered exception: {0}.\n".format(error.__class__.__name__))
			return True

		try:
			dmarc_policy = DMARCPolicy.from_domain(test_domain)
		except DMARCNoRecordError:
			self.logger.debug('no dmarc policy found for domain: ' + test_domain)
			text_insert('done, no policy found.\n')
			return True
		except DMARCError as error:
			self.logger.warning('dmarc error: ' + error.message)
			text_insert("done, encountered exception: {0}.\n".format(error.__class__.__name__))
			return False
		text_insert('done.\n')
		self.logger.debug("dmarc policy set to {0!r} for domain: {1}".format(dmarc_policy.policy, test_domain))
		text_insert('Found DMARC policy:\n')
		text_insert('  Policy:  ' + dmarc_policy.policy + '\n')
		text_insert('  Percent: ' + dmarc_policy.get('pct') + '\n')
		if dmarc_policy.get('rua'):
			text_insert('  RUA URI: ' + dmarc_policy.get('rua') + '\n')
		if dmarc_policy.get('ruf'):
			text_insert('  RUF URI: ' + dmarc_policy.get('ruf') + '\n')

		if spf_result == constants.SPFResult.PASS:
			return True
		if dmarc_policy.policy == 'none' or dmarc_policy.get('pct') == '0':
			return True

		if dmarc_policy.policy == 'quarantine':
			message = 'The DMARC policy results in these messages being quarantined.'
		elif dmarc_policy.policy == 'reject':
			message = 'The DMARC policy results in these messages being rejected.'
		text_insert('WARNING: ' + message + '\n')
		ignore = gui_utilities.show_dialog_yes_no(
			'DMARC Policy Failure',
			self.application.get_active_window(),
			message + '\nContinue sending messages anyways?'
		)
		return ignore

def main():
	parser = argparse.ArgumentParser(description='DMARC Check Utility', conflict_handler='resolve')
	parser.add_argument('domain', help='the name of the domain to check')
	arguments = parser.parse_args()

	policy = DMARCPolicy.from_domain(arguments.domain)
	print('record:  ' + policy.record)
	print('version: ' + policy.version)
	print('policy:  ' + policy.policy)

if __name__ == '__main__':
	main()
