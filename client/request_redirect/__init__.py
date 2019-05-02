import collections
import datetime
import functools
import ipaddress
import os

from king_phisher import serializers
from king_phisher.client import gui_utilities
from king_phisher.client import plugins
from king_phisher.client.widget import extras
from king_phisher.client.widget import managers

from gi.repository import GObject
from gi.repository import Gtk
import rule_engine

relpath = functools.partial(os.path.join, os.path.dirname(os.path.realpath(__file__)))
gtk_builder_file = relpath('request_redirect.ui')

_ModelNamedRow = collections.namedtuple('ModelNamedRow', (
	'index',
	'target',
	'permanent',
	'type',
	'text'
))

def named_row_to_entry(named_row):
	entry = {
		'permanent': named_row.permanent,
		'target': named_row.target,
		named_row.type.lower(): named_row.text
	}
	return entry

class _CellRendererIndex(getattr(extras, 'CellRendererPythonText', object)):
	python_value = GObject.Property(type=int, flags=GObject.ParamFlags.READWRITE)
	@staticmethod
	def render_python_value(value):
		if not isinstance(value, int):
			return
		return str(value + 1)

class Plugin(plugins.ClientPlugin):
	authors = ['Spencer McIntyre']
	title = 'Request Redirect'
	description = """
	Edit rules for the server "Request Redirect" plugin.
	"""
	homepage = 'https://github.com/securestate/king-phisher'
	req_min_version = '1.14.0b0'
	version = '1.0.0'
	def initialize(self):
		self.window = None
		if not os.access(gtk_builder_file, os.R_OK):
			gui_utilities.show_dialog_error(
				'Plugin Error',
				self.application.get_active_window(),
				"The GTK Builder data file ({0}) is not available.".format(os.path.basename(gtk_builder_file))
			)
			return False
		self._label_summary = None
		self._rule_context = None
		self._tv = None
		self._tv_model = Gtk.ListStore(int, str, bool, str, str)
		self._tv_model.connect('row-inserted', self.signal_model_multi)
		self._tv_model.connect('row-deleted', self.signal_model_multi)
		self.menu_items = {}
		self.menu_items['edit_rules'] = self.add_menu_item('Tools  > Request Redirect Rules', self.show_editor_window)
		return True

	def _editor_refresh(self):
		self.application.rpc.async_call(
			'plugins/request_redirect/rules/list',
			on_success=self.asyncrpc_list,
			when_idle=False
		)

	def _editor_delete(self, treeview, selection):
		(model, tree_iter) = selection.get_selected()
		if not tree_iter:
			return
		if not gui_utilities.show_dialog_yes_no('Delete This Entry?', self.window, 'Are you sure you want to delete this entry?'):
			return
		self.application.rpc.async_call(
			'plugins/request_redirect/rules/remove',
			(_ModelNamedRow(*model[tree_iter]).index,),
			on_success=self.asyncrpc_remove,
			when_idle=True,
			cb_args=(model, tree_iter)
		)

	def _update_remote_entry(self, path):
		named_row = _ModelNamedRow(*self._tv_model[path])
		entry = named_row_to_entry(named_row)
		self.application.rpc.async_call(
			'plugins/request_redirect/rules/set',
			(named_row.index, entry)
		)

	def finalize(self):
		if self.window is not None:
			self.window.destroy()

	def show_editor_window(self, _):
		self.application.rpc.async_graphql(
			'query getPlugin($name: String!) { plugin(name: $name) { version } }',
			query_vars={'name': self.name},
			on_success=self.asyncrpc_graphql,
			when_idle=True
		)

	def asyncrpc_graphql(self, plugin_info):
		if plugin_info['plugin'] is None:
			gui_utilities.show_dialog_error(
				'Missing Server Plugin',
				self.application.get_active_window(),
				'The server side plugin is missing. It must be installed and enabled by the server administrator.'
			)
			return
		if self.window is None:
			self.application.rpc.async_call(
				'plugins/request_redirect/rules/symbols',
				on_success=self.asyncrpc_symbols,
				when_idle=False
			)
			builder = Gtk.Builder()
			self.logger.debug('loading gtk builder file from: ' + gtk_builder_file)
			builder.add_from_file(gtk_builder_file)
			
			self.window = builder.get_object('RequestRedirect.editor_window')
			self.window.set_transient_for(self.application.get_active_window())
			self.window.connect('destroy', self.signal_window_destroy)
			self._tv = builder.get_object('RequestRedirect.treeview_editor')
			self._tv.set_model(self._tv_model)
			tvm = managers.TreeViewManager(self._tv, cb_delete=self._editor_delete, cb_refresh=self._editor_refresh)

			# target renderer
			target_renderer = Gtk.CellRendererText()
			target_renderer.set_property('editable', True)
			target_renderer.connect('edited', functools.partial(self.signal_renderer_edited, 'target'))

			# permanent renderer
			permanent_renderer = Gtk.CellRendererToggle()
			permanent_renderer.connect('toggled', functools.partial(self.signal_renderer_toggled, 'permanent'))

			# type renderer
			store = Gtk.ListStore(str)
			store.append(['Rule'])
			store.append(['Source'])
			type_renderer = Gtk.CellRendererCombo()
			type_renderer.set_property('editable', True)
			type_renderer.set_property('has-entry', False)
			type_renderer.set_property('model', store)
			type_renderer.set_property('text-column', 0)
			type_renderer.connect('edited', self.signal_renderer_edited_type)

			# text renderer
			text_renderer = Gtk.CellRendererText()
			text_renderer.set_property('editable', True)
			text_renderer.connect('edited', functools.partial(self.signal_renderer_edited, 'text'))

			tvm.set_column_titles(
				('#', 'Target', 'Permanent', 'Type', 'Text'),
				renderers=(
					_CellRendererIndex(),      # index
					target_renderer,           # Target
					permanent_renderer,        # Permanent
					type_renderer,             # Type
					text_renderer              # Text
				)
			)
			tvm.get_popup_menu()
			menu_item = builder.get_object('RequestRedirect.menuitem_export')
			menu_item.connect('activate', self.signal_menu_item_export)
			self._label_summary = builder.get_object('RequestRedirect.label_summary')
			self._editor_refresh()
		self.window.show()
		self.window.present()

	def asyncrpc_list(self, entries):
		things = []
		for idx, rule in enumerate(entries):
			if 'rule' in rule:
				type_ = 'Rule'
				text = rule['rule']
			elif 'source' in rule:
				type_ = 'Source'
				text = rule['source']
			else:
				self.logger.warning("rule #{0} contains neither a rule or source key".format(idx))
				continue
			things.append((idx, rule['target'], rule['permanent'], type_, text))
		gui_utilities.glib_idle_add_store_extend(self._tv_model, things, clear=True)

	def asyncrpc_remove(self, model, tree_iter, _):
		this_tree_iter = tree_iter
		tree_iter = model.iter_next(tree_iter)
		del model[this_tree_iter]
		index = _ModelNamedRow._fields.index('index')
		while tree_iter and model.iter_is_valid(tree_iter):
			model[tree_iter][index] = model[tree_iter][index] - 1
			tree_iter = model.iter_next(tree_iter)

	def asyncrpc_symbols(self, symbols):
		symbols = {k: getattr(rule_engine.DataType, v) for k, v in symbols.items()}
		type_resolver = rule_engine.type_resolver_from_dict(symbols)
		self._rule_context = rule_engine.Context(type_resolver=type_resolver)

	def signal_menu_item_export(self, _):
		dialog = extras.FileChooserDialog('Export Entries', self.window)
		response = dialog.run_quick_save('request_redirect.json')
		dialog.destroy()
		if not response:
			return
		entries = []
		for row in self._tv_model:
			named_row = _ModelNamedRow(*row)
			entries.append(named_row_to_entry(named_row))
		export = {
			'created': datetime.datetime.utcnow().isoformat() + '+00:00',
			'entries': entries
		}
		with open(response['target_path'], 'w') as file_h:
			serializers.JSON.dump(export, file_h)

	def signal_model_multi(self, model, *_):
		if self._label_summary is None:
			return
		self._label_summary.set_text("Showing {:,} Redirect Configuration{}".format(len(model), '' if len(model) == 1 else 's'))

	def signal_renderer_edited(self, field, _, path, text):
		text = text.strip()
		entry_type = self._tv_model[path][_ModelNamedRow._fields.index('type')].lower()
		if entry_type == 'source':
			try:
				ipaddress.ip_network(text)
			except ValueError:
				gui_utilities.show_dialog_error('Invalid Source', self.window, 'The specified text is not a valid IP network in CIDR notation.')
				return
		else:
			try:
				rule_engine.Rule(text, context=self._rule_context)
			except rule_engine.SymbolResolutionError as error:
				gui_utilities.show_dialog_error('Invalid Rule', self.window, "The specified rule text contains the unknown symbol {!r}.".format(error.symbol_name))
				return
			except rule_engine.SyntaxError:
				gui_utilities.show_dialog_error('Invalid Rule', self.window, 'The specified rule text contains a syntax error.')
				return
			except rule_engine.EngineError:
				gui_utilities.show_dialog_error('Invalid Rule', self.window, 'The specified text is not a valid rule.')
				return
		self._tv_model[path][_ModelNamedRow._fields.index(field)] = text
		self._update_remote_entry(path)

	def signal_renderer_edited_type(self, _, path, text):
		field_index = _ModelNamedRow._fields.index('type')
		if self._tv_model[path][field_index] == text:
			return
		self._tv_model[path][field_index] = text
		if text.lower() == 'source':
			self._tv_model[path][_ModelNamedRow._fields.index('text')] = '0.0.0.0/32'
		elif text.lower() == 'rule':
			self._tv_model[path][_ModelNamedRow._fields.index('text')] = 'false'
		self._update_remote_entry(path)

	def signal_renderer_toggled(self, field, _, path):
		index = _ModelNamedRow._fields.index(field)
		self._tv_model[path][index] = not self._tv_model[path][index]
		self._update_remote_entry(path)

	def signal_window_destroy(self, window):
		self.window = None
