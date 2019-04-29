import collections
import functools
import os

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
		self._loader_thread = None
		self._tv_model = Gtk.ListStore(int, str, bool, str, str)
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
		named_row = _ModelNamedRow(*model[tree_iter])
		if not gui_utilities.show_dialog_yes_no('Delete This Entry?', self.window, 'Are you sure you want to delete this entry?'):
			return
		self._rpc('remove', named_row.index)
		del model[tree_iter]

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

	def finalize(self):
		if self.window is not None:
			self.window.destroy()

	def show_editor_window(self, _):
		if self.window is None:
			self.window = self._get_object('editor_window')
			self.window.set_transient_for(self.application.get_active_window())
			self.window.connect('destroy', self.signal_window_destroy)
			treeview = self._get_object('treeview_editor')
			treeview.set_model(self._tv_model)
			tvm = managers.TreeViewManager(treeview, cb_delete=self._editor_delete, cb_refresh=self._editor_refresh)
			tvm.set_column_titles(
				('#', 'Target', 'Permanent', 'Type', 'Text'),
				renderers=(
					_CellRendererIndex(),      # index
					Gtk.CellRendererText(),    # Target
					Gtk.CellRendererToggle(),  # Permanent
					Gtk.CellRendererText(),    # Type
					Gtk.CellRendererText()     # Text
				)
			)
			self._editor_refresh()
		self.window.show()
		self.window.present()

	def signal_window_destroy(self, window):
		self.window = None
