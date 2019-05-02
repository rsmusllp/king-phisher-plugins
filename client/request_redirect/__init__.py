import collections
import datetime
import functools
import os

from king_phisher import serializers
from king_phisher import utilities
from king_phisher.client import gui_utilities
from king_phisher.client import plugins
from king_phisher.client.widget import extras
from king_phisher.client.widget import managers

from gi.repository import GObject
from gi.repository import Gtk

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
	req_min_version = '1.12'
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
		self._builder = None
		self._label_summary = None
		self._loader_thread = None
		self._tv_model = Gtk.ListStore(int, str, bool, str, str)
		self._tv_model.connect('row-inserted', self.signal_model_multi)
		self._tv_model.connect('row-deleted', self.signal_model_multi)
		self.menu_items = {}
		self.menu_items['edit_rules'] = self.add_menu_item('Tools  > Request Redirect Rules', self.show_editor_window)
		return True

	def _editor_refresh(self):
		if self._loader_thread and self._loader_thread.is_alive():
			self.logger.info('ignoring command to refresh because the loader thread is already running')
			return
		self._loader_thread = utilities.Thread(self._loader_routine)
		self._loader_thread.start()

	def _editor_delete(self, treeview, selection):
		(model, tree_iter) = selection.get_selected()
		if not tree_iter:
			return
		if not gui_utilities.show_dialog_yes_no('Delete This Entry?', self.window, 'Are you sure you want to delete this entry?'):
			return
		self._rpc('remove', _ModelNamedRow(*model[tree_iter]).index)
		this_tree_iter = tree_iter
		tree_iter = model.iter_next(tree_iter)
		del model[this_tree_iter]
		index = _ModelNamedRow._fields.index('index')
		while tree_iter and model.iter_is_valid(tree_iter):
			model[tree_iter][index] = model[tree_iter][index] - 1
			tree_iter = model.iter_next(tree_iter)

	def _get_object(self, name):
		if self._builder is None:
			self._builder = Gtk.Builder()
			self.logger.debug('loading gtk builder file from: ' + gtk_builder_file)
			self._builder.add_from_file(gtk_builder_file)
		return self._builder.get_object('RequestRedirect.' + name)

	def _loader_routine(self):
		rules = self._rpc('list')
		things = []
		for idx, rule in enumerate(rules):
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

	def _rpc(self, method, *args, **kwargs):
		method = 'plugins/request_redirect/rules/' + method
		return self.application.rpc(method, *args, **kwargs)

	def _update_remote_entry(self, path):
		named_row = _ModelNamedRow(*self._tv_model[path])
		entry = named_row_to_entry(named_row)
		self._rpc('set', named_row.index, entry)

	def finalize(self):
		if self.window is not None:
			self.window.destroy()

	def show_editor_window(self, _):
		if self.window is None:
			self._builder = None
			self.window = self._get_object('editor_window')
			self.window.set_transient_for(self.application.get_active_window())
			self.window.connect('destroy', self.signal_window_destroy)
			treeview = self._get_object('treeview_editor')
			treeview.set_model(self._tv_model)
			tvm = managers.TreeViewManager(treeview, cb_delete=self._editor_delete, cb_refresh=self._editor_refresh)

			# target renderer
			target_renderer = Gtk.CellRendererText()
			target_renderer.set_property('editable', True)
			target_renderer.connect('edited', functools.partial(self.signal_multi_edited, 'target'))

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
			type_renderer.connect('edited', functools.partial(self.signal_multi_edited, 'type'))

			# text renderer
			text_renderer = Gtk.CellRendererText()
			text_renderer.set_property('editable', True)
			text_renderer.connect('edited', functools.partial(self.signal_multi_edited, 'text'))

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
			menu_item = self._get_object('menuitem_export')
			menu_item.connect('activate', self.signal_menu_item_export)
			self._label_summary = self._get_object('label_summary')
			self._editor_refresh()
		self.window.show()
		self.window.present()

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

	def signal_multi_edited(self, field, _, path, text):
		text = text.strip()
		self._tv_model[path][_ModelNamedRow._fields.index(field)] = text
		self._update_remote_entry(path)

	def signal_renderer_toggled(self, field, _, path):
		index = _ModelNamedRow._fields.index(field)
		self._tv_model[path][index] = not self._tv_model[path][index]
		self._update_remote_entry(path)

	def signal_window_destroy(self, window):
		self.window = None
