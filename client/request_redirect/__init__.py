import collections
import functools
import os

import king_phisher.client.plugins as plugins
import king_phisher.client.gui_utilities as gui_utilities
import king_phisher.client.widget.managers as managers

from gi.repository import Gtk

relpath = functools.partial(os.path.join, os.path.dirname(os.path.realpath(__file__)))
gtk_builder_file = relpath('request_redirect.ui')

class Plugin(plugins.ClientPlugin):
	authors = ['Spencer McIntyre']
	title = 'Request Redirect'
	description = """

	"""
	homepage = 'https://github.com/securestate/king-phisher-plugins'
	req_min_version = '1.10.0'
	version = '1.0'
	_RowModel = collections.namedtuple('RowModel', (
		'permanent',
		'rule',
		'source',
		'target',
	))
	def initialize(self):
		if not os.access(gtk_builder_file, os.R_OK):
			gui_utilities.show_dialog_error(
				'Plugin Error',
				self.application.get_active_window(),
				"The GTK Builder data file ({0}) is not available.".format(os.path.basename(gtk_builder_file))
			)
			return False
		self.window = None
		self.menu_items = {}
		self.menu_items['redirect_rules'] = self.add_menu_item('Tools > Request Redirect Rules', self.show_rules_window)
		return True

	def finalize(self):
		if self.window is not None:
			self.window.destroy()

	def _init_treeview(self, treeview):
		self._tv_model = Gtk.ListStore(str, str, str, bool)
		treeview.set_model(self._tv_model)
		self.treeview_manager = managers.TreeViewManager(
			treeview,
			selection_mode=None,#Gtk.SelectionMode.MULTIPLE,
			cb_delete=self._tv_delete,
			cb_refresh=self._tv_refresh
		)
		self.treeview_manager.set_column_titles(
			('Source', 'Rule', 'Target', 'Permanent'),
			renderers=(
				Gtk.CellRendererText(),
				Gtk.CellRendererText(),
				Gtk.CellRendererText(),
				Gtk.CellRendererToggle()
			)
		)
		self.popup_menu = self.treeview_manager.get_popup_menu()
		self._tv_refresh()

	def _rpc_call(self, method, *args, **kwargs):
		return self.application.rpc('plugins/request_redirect/rules/' + method, *args, **kwargs)

	def _tv_delete(self, treeview, selection):
		(model, tree_iter) = selection.get_selected()
		if not tree_iter:
			return
		if not gui_utilities.show_dialog_yes_no('Delete This Rule?', self.window, 'Are you sure you want to delete this rule?'):
			return
		path = model.get_path(tree_iter)
		index = path.get_indices()[0]
		self._rpc_call('remove', index)
		del model[path]

	def _tv_refresh(self):
		self._tv_model.clear()
		for redirect_rule in self._rpc_call('list'):
			redirect_rule = self._RowModel(**redirect_rule)
			self._tv_model.append((
				redirect_rule.source,
				redirect_rule.rule,
				redirect_rule.target,
				redirect_rule.permanent
			))

	def show_rules_window(self, _):
		if self.window is None:
			self.logger.debug('loading gtk builder file from: ' + gtk_builder_file)
			builder = Gtk.Builder()
			builder.add_from_file(gtk_builder_file)
			builder.connect_signals(self)
			self.window = builder.get_object('RequestRedirect.window')
			self.window.set_transient_for(self.application.get_active_window())
			self.application.add_window(self.window)
			self._init_treeview(builder.get_object('RequestRedirect.treeview_rules'))
			self.window.connect('destroy', self.signal_window_destroy)
		self.window.show()
		self.window.present()

	def signal_window_destroy(self, window):
		self.window = None
