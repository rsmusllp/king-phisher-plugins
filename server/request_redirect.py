import ipaddress

import king_phisher.errors as errors
import king_phisher.server.plugins as plugins
import king_phisher.server.server_rpc as server_rpc
import king_phisher.server.signals as signals

try:
	import rule_engine
except ImportError:
	has_rule_engine = False
else:
	has_rule_engine = True

EXAMPLE_CONFIG = """\
rules:
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
	rule_types = {
		'accept': rule_engine.DataType.STRING,
		'dst_addr': rule_engine.DataType.STRING,
		'dst_port': rule_engine.DataType.FLOAT,
		'path': rule_engine.DataType.STRING,
		'src_addr': rule_engine.DataType.STRING,
		'src_port': rule_engine.DataType.FLOAT,
		'user_agent': rule_engine.DataType.STRING,
		'verb': rule_engine.DataType.STRING,
		'vhost': rule_engine.DataType.STRING,
	}
	def initialize(self):
		self._context = rule_engine.Context(
			resolver=_context_resolver,
			type_resolver=rule_engine.type_resolver_from_dict(self.rule_types)
		)
		for idx, rule in enumerate(self.rules, 1):
			if 'rule' in rule:
				rule['rule'] = rule_engine.Rule(rule['rule'], context=self._context)
			elif 'source' in rule:
				rule['source'] = ipaddress.ip_network(rule['source'])
			else:
				raise RuntimeError("rule #{0} contains neither a rule or source key".format(idx))
			rule['permanent'] = rule.get('permanent', True)
		signals.request_handle.connect(self.on_request_handle)
		self.logger.info("initialized with {0:,} redirect rules".format(len(self.rules)))

		rpc_api_base = '/plugins/request_redirect/rules/'
		server_rpc.register_rpc(rpc_api_base + 'insert')(self._rpc_request_insert)
		server_rpc.register_rpc(rpc_api_base + 'list')(self._rpc_request_list)
		server_rpc.register_rpc(rpc_api_base + 'remove')(self._rpc_request_remove)
		server_rpc.register_rpc(rpc_api_base + 'set')(self._rpc_request_set)
		server_rpc.register_rpc(rpc_api_base + 'symbols')(self._rpc_request_symbols)
		return True

	def _process_rule(self, rule, index=None):
		if 'rule' in rule:
			rule['rule'] = rule_engine.Rule(rule['rule'], context=self._context)
		elif 'source' in rule:
			rule['source'] = ipaddress.ip_network(rule['source'])
		else:
			raise RuntimeError("rule {}contains neither a rule or source key".format('' if index is None else '#' + str(index)))
		return rule

	def _rpc_request_insert(self, handler, index, rule):
		rule = self._process_rule(rule, index)
		self.rules.insert(index, rule)

	def _rpc_request_list(self, handler):
		rules = []
		for rule in self.rules:
			rule = dict(rule)  # shallow copy
			if 'rule' in rule:
				rule['rule'] = rule['rule'].text
			if 'source' in rule:
				rule['source'] = str(rule['source'])
			rules.append(rule)
		return rules

	def _rpc_request_remove(self, handler, index):
		del self.rules[index]

	def _rpc_request_set(self, handler, index, rule):
		rule = self._process_rule(rule, index)
		self.rules[index] = rule

	def _rpc_request_symbols(self, handler):
		return {key: value.type for key, value in self.rule_types.items()}

	@property
	def rules(self):
		if not 'rules' in self.config:
			self.config['rules'] = []
		return self.config['rules']

	def on_request_handle(self, handler):
		if handler.command == 'RPC' or handler.path.startswith('/_/'):
			return
		client_ip = ipaddress.ip_address(handler.client_address[0])
		for rule in self.rules:
			if 'rule' in rule and not rule['rule'].matches(handler):
				continue
			if 'source' in rule and client_ip not in rule['source']:
				continue
			target = rule.get('target')
			if not target:
				self.logger.debug("request redirect rule for {0} matched exception".format(str(client_ip)))
				break
			self.logger.debug("request redirect rule for {0} matched target: {1}".format(str(client_ip), target))
			self.respond_redirect(handler, rule)
			raise errors.KingPhisherAbortRequestError(response_sent=True)

	def respond_redirect(self, handler, rule):
		handler.send_response(301 if rule['permanent'] else 302)
		handler.send_header('Content-Length', 0)
		handler.send_header('Location', rule['target'])
		handler.end_headers()
