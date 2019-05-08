import functools
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
# the optional access level to require for users to change entries
access_level_write: 1000
entries:
  # first entry is an exception because no target is specified
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
		return handler.server.socket.getsockname()[0]
	elif name == 'dst_port':
		return handler.server.socket.getsockname()[1]
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

def check_access_level(function):
	@functools.wraps(function)
	def wrapped(plugin, handler, *args, **kwargs):
		if not plugin.handler_has_write_access(handler):
			raise errors.KingPhisherPermissionError('the user does not possess the necessary access level to change this data')
		return function(plugin, handler, *args, **kwargs)
	return wrapped

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
	req_min_version = '1.14.0b0'
	req_packages = {
		'rule-engine': has_rule_engine
	}
	version = '2.0'
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
		self._pending = set()
		signals.server_initialized.connect(self.on_server_initialized)
		signals.rpc_user_logged_out.connect(self.on_rpc_user_logged_out)
		return True

	def _entry_from_raw(self, entry, index=None):
		entry = entry.copy()
		if 'rule' in entry:
			entry['rule'] = rule_engine.Rule(entry['rule'], context=self._context)
		elif 'source' in entry:
			entry['source'] = ipaddress.ip_network(entry['source'])
		else:
			raise RuntimeError("rule {}contains neither a rule or source key".format('' if index is None else '#' + str(index) + ' '))
		entry['permanent'] = entry.get('permanent', True)
		return entry

	def _entry_to_raw(self, entry):
		entry = entry.copy()
		if 'rule' in entry:
			entry['rule'] = str(entry['rule'])
		if 'source' in entry:
			entry['source'] = str(entry['source'])
		return entry

	@check_access_level
	def _rpc_request_entries_insert(self, handler, index, rule):
		rule = self._entry_from_raw(rule, index)
		self.entries.insert(index, rule)
		self._pending.add(handler.rpc_session_id)

	def _rpc_request_entries_list(self, handler):
		rules = []
		for rule in self.entries:
			rule = dict(rule)  # shallow copy
			if 'rule' in rule:
				rule['rule'] = rule['rule'].text
			if 'source' in rule:
				rule['source'] = str(rule['source'])
			rules.append(rule)
		return rules

	def _rpc_request_permissions(self, handler):
		permissions = ['read']
		if self.handler_has_write_access(handler):
			permissions.append('write')
		return permissions

	@check_access_level
	def _rpc_request_entries_remove(self, handler, index):
		del self.entries[index]
		self._pending.add(handler.rpc_session_id)

	@check_access_level
	def _rpc_request_entries_set(self, handler, index, rule):
		rule = self._entry_from_raw(rule, index)
		self.entries[index] = rule
		self._pending.add(handler.rpc_session_id)

	def _rpc_request_symbols(self, handler):
		return {key: value.name for key, value in self.rule_types.items()}

	def _store_entries(self):
		self.logger.info("storing {:,} request redirect entries to the database storage".format(len(self.entries)))
		self.storage['entries'] = [self._entry_to_raw(entry) for entry in self.entries]

	def finalize(self):
		self._store_entries()

	def handler_has_write_access(self, handler):
		access_level = self.config.get('access_level_write')
		if access_level is None:
			return True
		return handler.rpc_session.user_access_level <= access_level

	def on_request_handle(self, handler):
		if handler.command == 'RPC' or handler.path.startswith('/_/'):
			return
		client_ip = ipaddress.ip_address(handler.client_address[0])
		for entry in self.entries:
			if 'rule' in entry and not entry['rule'].matches(handler):
				continue
			if 'source' in entry and client_ip not in entry['source']:
				continue
			target = entry.get('target')
			if not target:
				self.logger.debug("request redirect rule for {0} matched exception".format(str(client_ip)))
				break
			self.logger.debug("request redirect rule for {0} matched target: {1}".format(str(client_ip), target))
			self.respond_redirect(handler, entry)
			raise errors.KingPhisherAbortRequestError(response_sent=True)

	def on_rpc_user_logged_out(self, handler, session, name):
		if session not in self._pending:
			return
		self._pending.remove(session)
		self._store_entries()

	def on_server_initialized(self, server):
		entries = self.config.get('entries', [])
		if entries:
			self.logger.debug("loaded request redirect entries from the configuration".format(len(entries)))
		else:
			entries = self.storage.get('entries', [])
			if entries:
				self.logger.debug("loaded request redirect entries from the database storage".format(len(entries)))
		self.entries = []
		for idx, entry in enumerate(entries, 1):
			self.entries.append(self._entry_from_raw(entry, idx))

		signals.request_handle.connect(self.on_request_handle)
		self.logger.info("initialized with {0:,} redirect entries".format(len(self.entries)))

		rpc_api_base = '/plugins/request_redirect/'
		server_rpc.register_rpc(rpc_api_base + 'entries/insert')(self._rpc_request_entries_insert)
		server_rpc.register_rpc(rpc_api_base + 'entries/list')(self._rpc_request_entries_list)
		server_rpc.register_rpc(rpc_api_base + 'entries/remove')(self._rpc_request_entries_remove)
		server_rpc.register_rpc(rpc_api_base + 'entries/set')(self._rpc_request_entries_set)
		server_rpc.register_rpc(rpc_api_base + 'permissions')(self._rpc_request_permissions)
		server_rpc.register_rpc(rpc_api_base + 'rule_symbols')(self._rpc_request_symbols)

	def respond_redirect(self, handler, rule):
		handler.send_response(301 if rule['permanent'] else 302)
		handler.send_header('Content-Length', 0)
		handler.send_header('Location', rule['target'])
		handler.end_headers()
