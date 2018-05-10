import ipaddress

import king_phisher.errors as errors
import king_phisher.server.plugins as plugins
import king_phisher.server.signals as signals

EXAMPLE_CONFIG = """\
rules:
  # first rule is an exception because no target is specified
  - source: 192.168.0.0/16
  # second rule redirects all ipv4 addresses to google
  - source: 0.0.0.0/0
    target: https://www.google.com
    permanent: false
"""

class Plugin(plugins.ServerPlugin):
	authors = ['Spencer McIntyre']
	title = 'Request Redirect'
	description = """
	A plugin that allows requests to be redirected based on a matching source
	IP address or Range. This can be useful for redirecting known ranges of
	systems which maybe analyzing the server.
	Rules are processed in order and each one is a hash with at least a source
	key of an IP address or network. Additionally a target string will be used
	as the destination of the redirect or can be left as null for an exception.
	Finally, a boolean key of permanent can be used to specify whether a 301 or
	302 redirect should be used.
	"""
	homepage = 'https://github.com/securestate/king-phisher-plugins'
	req_min_version = '1.9.0'
	version = '1.0.1'
	def initialize(self):
		rules = self.config.get('rules', [])
		for rule in rules:
			rule['source'] = ipaddress.ip_network(rule['source'])
		signals.request_handle.connect(self.on_request_handle)
		self.logger.info("initialized with {0:,} redirect rules".format(len(rules)))
		return True

	def on_request_handle(self, handler):
		if handler.command == 'RPC' or handler.path.startswith('/_/'):
			return
		client_ip = ipaddress.ip_address(handler.client_address[0])
		for rule in self.config.get('rules', []):
			if client_ip not in rule['source']:
				continue
			target = rule.get('target')
			if not target:
				self.logger.debug("request redirect rule for {0} matched exception".format(str(client_ip)))
				break
			self.logger.debug("request redirect rule for {0} matched target: {1}".format(str(client_ip), target))
			self.respond_redirect(handler, rule)
			raise errors.KingPhisherAbortRequestError(response_sent=True)

	def respond_redirect(self, handler, rule):
		handler.send_response(301 if rule.get('permanent', True) else 302)
		handler.send_header('Content-Length', 0)
		handler.send_header('Location', rule['target'])
		handler.end_headers()
