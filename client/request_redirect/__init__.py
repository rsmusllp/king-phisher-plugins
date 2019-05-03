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
import jsonschema
import rule_engine
import rule_engine.errors

relpath = functools.partial(os.path.join, os.path.dirname(os.path.realpath(__file__)))
gtk_builder_file = relpath('request_redirect.ui')
json_schema_file = relpath('schema.json')

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

def _update_model_indexes(model, starting, modifier):
	for row in model:
		named_row = _ModelNamedRow(*row)
		if named_row.index < starting:
			continue
		model[row.iter][_ModelNamedRow._fields.index('index')] += modifier

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
			'plugins/request_redirect/entries/list',
			on_success=self.asyncrpc_list,
			when_idle=False
		)

	def _editor_delete(self, treeview, selection):
		selection = treeview.get_selection()
		(model, tree_paths) = selection.get_selected_rows()
		if not tree_paths:
			return
		rows = []
		for tree_path in tree_paths:
			rows.append((_ModelNamedRow(*model[tree_path]).index, Gtk.TreeRowReference.new(model, tree_path)))
		if len(rows) == 1:
			message = 'Delete This Row?'
		else:
			message = "Delete These {0:,} Rows?".format(len(rows))
		if not gui_utilities.show_dialog_yes_no(message, self.window, 'This information will be lost.'):
			return

		rows = reversed(sorted(rows, key=lambda item: item[0]))
		for row_index, row_ref in rows:
			self.application.rpc.async_call(
				'plugins/request_redirect/entries/remove',
				(row_index,),
				on_success=self.asyncrpc_remove,
				when_idle=True,
				cb_args=(model, row_ref)
			)

	def _update_remote_entry(self, path):
		named_row = _ModelNamedRow(*self._tv_model[path])
		entry = named_row_to_entry(named_row)
		self.application.rpc.async_call(
			'plugins/request_redirect/entries/set',
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
		self.application.rpc.async_call(
			'plugins/request_redirect/permissions',
			on_success=self.asyncrpc_permissions,
			when_idle=True
		)

	def asyncrpc_permissions(self, permissions):
		writable = 'write' in permissions
		if self.window is None:
			self.application.rpc.async_call(
				'plugins/request_redirect/rule_symbols',
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
			tvm = managers.TreeViewManager(
				self._tv,
				cb_delete=(self._editor_delete if writable else None),
				cb_refresh=self._editor_refresh,
				selection_mode=Gtk.SelectionMode.MULTIPLE,
			)

			# target renderer
			target_renderer = Gtk.CellRendererText()
			if writable:
				target_renderer.set_property('editable', True)
				target_renderer.connect('edited', functools.partial(self.signal_renderer_edited, 'target'))

			# permanent renderer
			permanent_renderer = Gtk.CellRendererToggle()
			if writable:
				permanent_renderer.connect('toggled', functools.partial(self.signal_renderer_toggled, 'permanent'))

			# type renderer
			store = Gtk.ListStore(str)
			store.append(['Rule'])
			store.append(['Source'])
			type_renderer = Gtk.CellRendererCombo()
			type_renderer.set_property('has-entry', False)
			type_renderer.set_property('model', store)
			type_renderer.set_property('text-column', 0)
			if writable:
				type_renderer.set_property('editable', True)
				type_renderer.connect('edited', self.signal_renderer_edited_type)

			# text renderer
			text_renderer = Gtk.CellRendererText()
			if writable:
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
			# treeview right-click menu
			menu = tvm.get_popup_menu()
			if writable:
				menu_item = Gtk.MenuItem.new_with_label('Insert')
				menu_item.connect('activate', self.signal_menu_item_insert)
				menu_item.show()
				menu.append(menu_item)

			# top menu bar
			menu_item = builder.get_object('RequestRedirect.menuitem_import')
			menu_item.connect('activate', self.signal_menu_item_import)
			menu_item.set_sensitive(writable)
			menu_item = builder.get_object('RequestRedirect.menuitem_export')
			menu_item.connect('activate', self.signal_menu_item_export)

			infobar = builder.get_object('RequestRedirect.infobar_read_only_warning')
			infobar.set_revealed(not writable)
			button = builder.get_object('RequestRedirect.button_read_only_acknowledgment')
			button.connect('clicked', lambda _: infobar.set_revealed(False))

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

	def asyncrpc_remove(self, model, row_ref, _):
		tree_path = row_ref.get_path()
		if tree_path is None:
			return
		old_index = _ModelNamedRow(*model[tree_path]).index
		del model[tree_path]
		_update_model_indexes(model, old_index, -1)

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

	def signal_menu_item_import(self, _):
		dialog = extras.FileChooserDialog('Import Entries', self.window)
		dialog.quick_add_filter('Data Files', '*.json')
		dialog.quick_add_filter('All Files', '*')
		response = dialog.run_quick_open()
		dialog.destroy()
		if not response:
			return
		try:
			with open(response['target_path'], 'r') as file_h:
				data = serializers.JSON.load(file_h)
		except Exception:
			gui_utilities.show_dialog_error(
				'Import Failed',
				self.window,
				'Could not load the specified file.'
			)
			return
		with open(json_schema_file, 'r') as file_h:
			schema = serializers.JSON.load(file_h)
		try:
			jsonschema.validate(data, schema)
		except jsonschema.exceptions.ValidationError:
			gui_utilities.show_dialog_error(
				'Import Failed',
				self.window,
				'Could not load the specified file, the data is malformed.'
			)
			return
		cursor = len(self._tv_model)
		for entry in data['entries']:
			if 'rule' in entry:
				entry_type = 'Rule'
				text = entry['rule']
			elif 'source' in entry:
				entry_type = 'Source'
				text = entry['source']
			new_named_row = _ModelNamedRow(cursor, entry['target'], entry['permanent'], entry_type, text)
			self.application.rpc.async_call(
				'plugins/request_redirect/entries/insert',
				(cursor, named_row_to_entry(new_named_row))
			)
			self._tv_model.append(new_named_row)
			cursor += 1

	def signal_menu_item_insert(self, _):
		selection = self._tv.get_selection()
		new_named_row = _ModelNamedRow(len(self._tv_model), '', True, 'Source', '0.0.0.0/32')
		if selection.count_selected_rows() == 0:
			self._tv_model.append(new_named_row)
		elif selection.count_selected_rows() == 1:
			(model, tree_paths) = selection.get_selected_rows()
			tree_iter = model.get_iter(tree_paths[0])
			new_named_row = new_named_row._replace(index=_ModelNamedRow(*model[tree_iter]).index)
			_update_model_indexes(model, new_named_row.index, 1)
			self._tv_model.insert_before(tree_iter, new_named_row)
		else:
			gui_utilities.show_dialog_error(
				'Can Not Insert Entry',
				self.window,
				'Can not insert a new entry when multiple entries are selected.'
			)
			return

		entry = named_row_to_entry(new_named_row)
		self.application.rpc.async_call(
			'plugins/request_redirect/entries/set',
			(new_named_row.index, entry)
		)

	def signal_model_multi(self, model, *_):
		if self._label_summary is None:
			return
		self._label_summary.set_text("Showing {:,} Redirect Configuration{}".format(len(model), '' if len(model) == 1 else 's'))

	def signal_renderer_edited(self, field, _, path, text):
		text = text.strip()
		if field == 'text':
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
				except rule_engine.errors.SyntaxError:
					gui_utilities.show_dialog_error('Invalid Rule', self.window, 'The specified rule text contains a syntax error.')
					return
				except rule_engine.errors.EngineError:
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
