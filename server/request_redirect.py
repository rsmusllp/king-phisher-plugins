import collections
import ipaddress

import king_phisher.errors as errors
import king_phisher.utilities as utilities
import king_phisher.server.plugins as plugins
import king_phisher.server.signals as signals

try:
	import rule_engine
except ImportError:
	has_rule_engine = False
else:
	has_rule_engine = True

EXAMPLE_CONFIG = """\
redirect_rules:
  # first rule is an exception because no target is specified
  - source: 192.168.0.0/16
  # second rule redirects all ipv4 addresses to google
  - source: 0.0.0.0/0
    target: https://www.google.com
    permanent: false
"""

def _context_resolver(handler, name):
	if name == 'accept':
		return handler.headers.get('Accept', '')
	elif name == 'dst_addr':
		return handler.socket.getsockname()[0]
	elif name == 'dst_port':
		return handler.socket.getsockname()[1]
	elif name == 'path':
		return handler.request_path
	elif name == 'src_addr':
		return handler.client_address[0]
	elif name == 'src_port':
		return handler.client_address[1]
	elif name == 'user_agent':
		return handler.headers.get('User-Agent', '')
	elif name == 'verb':
		return handler.command
	elif name == 'vhost':
		return handler.vhost
	raise rule_engine.SymbolResolutionError(name)

RedirectRule = collections.namedtuple('RedirectRule', ('permanent', 'rule', 'source', 'target'))

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
	req_packages = {
		'rule-engine': has_rule_engine
	}
	version = '1.1'
	def initialize(self):
		self._context = rule_engine.Context(
			resolver=_context_resolver,
			type_resolver=rule_engine.type_resolver_from_dict({
				'accept': rule_engine.DataType.STRING,
				'dst_addr': rule_engine.DataType.STRING,
				'dst_port': rule_engine.DataType.FLOAT,
				'path': rule_engine.DataType.STRING,
				'src_addr': rule_engine.DataType.STRING,
				'src_port': rule_engine.DataType.FLOAT,
				'user_agent': rule_engine.DataType.STRING,
				'verb': rule_engine.DataType.STRING,
				'vhost': rule_engine.DataType.STRING,
			})
		)
		self.redirect_rules = []
		for index, redirect_rule in enumerate(self.config.get('rules', [])):
			self._insert_redirect_rule(index, redirect_rule)
		signals.request_handle.connect(self.on_request_handle)
		self.logger.info("initialized with {0:,} redirect redirect_rules".format(len(self.redirect_rules)))

		self.register_rpc('rules/insert', self._rpc_request_insert)
		self.register_rpc('rules/list', self._rpc_request_list)
		self.register_rpc('rules/remove', self._rpc_request_remove)
		return True

	def _insert_redirect_rule(self, index, redirect_rule):
		if 'rule' in redirect_rule:
			redirect_rule['rule'] = rule_engine.Rule(redirect_rule['rule'], context=self._context)
		if 'source' in redirect_rule:
			redirect_rule['source'] = ipaddress.ip_network(redirect_rule['source'])
		if 'rule' not in redirect_rule and 'source' not in redirect_rule:
			raise RuntimeError("rule index {0} contains neither a rule or source key".format(index))
		self.redirect_rules.insert(index, RedirectRule(
			permanent=redirect_rule.get('permanent', True),
			rule=redirect_rule.get('rule'),
			source=redirect_rule.get('source'),
			target=utilities.nonempty_string(redirect_rule.get('target'))
		))

	def _rpc_request_insert(self, handler, index, redirect_rule):
		self._insert_redirect_rule(index, redirect_rule)

	def _rpc_request_list(self, handler):
		redirect_rules = []
		for redirect_rule in self.redirect_rules:
			redirect_rule = redirect_rule._asdict()
			if redirect_rule.get('rule'):
				redirect_rule['rule'] = str(redirect_rule['rule'])
			if redirect_rule.get('source'):
				redirect_rule['source'] = str(redirect_rule['source'])
			redirect_rules.append(redirect_rule)
		return redirect_rules

	def _rpc_request_remove(self, handler, index):
		del self.redirect_rules[index]

	def on_request_handle(self, handler):
		if handler.command == 'RPC' or handler.path.startswith('/_/'):
			return
		client_ip = ipaddress.ip_address(handler.client_address[0])
		for redirect_rule in self.redirect_rules:
			if redirect_rule.rule and not redirect_rule.matches(handler):
				continue
			if redirect_rule.source and client_ip not in redirect_rule.source:
				continue
			if redirect_rule.target is None:
				self.logger.debug("request redirect rule for {0} matched exception".format(str(client_ip)))
				break
			self.logger.debug("request redirect rule for {0} matched target: {1}".format(str(client_ip), redirect_rule.target))
			self.respond_redirect(handler, redirect_rule)
			raise errors.KingPhisherAbortRequestError(response_sent=True)

	def respond_redirect(self, handler, redirect_rule):
		handler.send_response(301 if redirect_rule.permanent else 302)
		handler.send_header('Content-Length', 0)
		handler.send_header('Location', redirect_rule.target)
		handler.end_headers()
