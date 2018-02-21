import datetime
import os

import king_phisher.find as find
import king_phisher.serializers as serializers
import king_phisher.client.application as application
import king_phisher.client.plugins as plugins
import king_phisher.client.gui_utilities as gui_utilities

def is_managed_key(key):
	"""
	Return True for configuration keys which should be managed by this
	plugin. This is to let keys for other configuration settings remain the
	same.

	:param str key: The name of the configuration key.
	:return: Whether or not the key should be managed by this plugin.
	:rtype: bool
	"""
	if key == 'mailer.company_name':
		return False
	if key.startswith('mailer.'):
		return True
	if key in ('remove_attachment_metadata', 'spf_check_level'):
		return True
	return False

class Plugin(plugins.ClientPlugin):
	authors = ['Spencer McIntyre']
	title = 'Campaign Message Configuration Manager'
	description = """
	Store campaign message configurations for their respective campaigns. This
	allows users to switch between campaigns while keeping each of the message
	configurations and restoring them when the user returns to the original
	campaign. New campaigns can either be created with customizable default
	settings or from the existing configuration (see the "Transfer Settings"
	option).
	"""
	homepage = 'https://github.com/securestate/king-phisher-plugins'
	options = [
		plugins.ClientOptionBoolean(
			'transfer_options',
			'Whether or not to keep the current settings for new campaigns.',
			default=True,
			display_name='Transfer Settings'
		)
	]
	req_min_version = '1.10.0b1'
	version = '1.0.1'
	def initialize(self):
		self.signal_connect('campaign-set', self.signal_kpc_campaign_set)
		self.storage = self.load_storage()

		# create the submenu for setting and clearing the default config
		submenu = 'Tools > Message Configuration'
		self.add_submenu(submenu)
		self.menu_items = {
			'set_defaults': self.add_menu_item(submenu + ' > Set Defaults', self.menu_item_set_defaults),
			'clear_defaults': self.add_menu_item(submenu + ' > Clear Defaults', self.menu_item_clear_defaults)
		}
		return True

	def finalize(self):
		self.set_campaign_config(self.get_current_config(), self.application.config['campaign_id'])
		self.save_storage()

	def menu_item_clear_defaults(self, _):
		proceed = gui_utilities.show_dialog_yes_no(
			'Clear Default Campaign Configuration?',
			self.application.get_active_window(),
			'Are you sure you want to clear the default\n'\
			 + 'message configuration for new campaigns?'
		)
		if not proceed:
			return
		self.storage['default'] = {}

	def menu_item_set_defaults(self, _):
		proceed = gui_utilities.show_dialog_yes_no(
			'Set The Default Campaign Configuration?',
			self.application.get_active_window(),
			'Are you sure you want to set the default\n'\
			 + 'message configuration for new campaigns?'
		)
		if not proceed:
			return
		self.storage['default'] = self.get_current_config()

	@property
	def storage_file_path(self):
		"""The path on disk of where to store the plugin's data."""
		return os.path.join(self.application.user_data_path, 'campaign_message_config.json')

	def load_default_config(self):
		"""
		Load the default configuration to use when settings are missing. This
		will load the user's configured defaults and fail back to the core ones
		distributed with the application.

		:return: The default configuration.
		:rtype: dict
		"""
		default_client_config = find.data_file('client_config.json')
		with open(default_client_config, 'r') as tmp_file:
			default_client_config = serializers.JSON.load(tmp_file)

		users_defaults = self.storage['default']
		for key, value in users_defaults.items():
			if not is_managed_key(key):
				continue
			if key not in default_client_config:
				continue
			default_client_config[key] = value
		return default_client_config

	def load_storage(self):
		"""
		Load this plugin's stored data from disk.

		:return: The plugin's stored data.
		:rtype: dict
		"""
		storage = {'campaigns': {}, 'default': {}}
		file_path = self.storage_file_path
		if os.path.isfile(file_path) and os.access(file_path, os.R_OK):
			self.logger.debug('loading campaign messages configuration file: ' + file_path)
			with open(file_path, 'r') as file_h:
				storage = serializers.JSON.load(file_h)
		else:
			self.logger.debug('campaigns configuration file not found')
		return storage

	def save_storage(self):
		"""Save this plugin's stored data to disk."""
		file_path = self.storage_file_path
		self.logger.debug('writing campaign messages configuration file: ' + file_path)
		with open(file_path, 'w') as file_h:
			serializers.JSON.dump(self.storage, file_h, pretty=True)

	def get_campaign_config(self, campaign_id=None):
		"""
		Get the message configuration for a specific campaign. If *campaign_id*
		is not specified, then the current campaign is used. If not settings
		are available for the specified campaign, an empty dictionary is
		returned.

		:param str campaign_id: The ID of the campaign.
		:return: The campaign's message configuration or an empty dictionary.
		:rtype: dict
		"""
		if campaign_id is None:
			campaign_id = self.application.config['campaign_id']
		campaign_id = str(campaign_id)
		if not self.storage.get('campaigns'):
			return {}
		return self.storage['campaigns'].get(campaign_id, {}).get('configuration')

	def set_campaign_config(self, config, campaign_id=None):
		"""
		Add the message configuration into the plugin's storage data and
		associate it with the specified campaign. If *campaign_id* is not
		specified, then the current campaign is used.

		:param dict config:
		:param str campaign_id: The ID of the campaign.
		"""
		if campaign_id is None:
			campaign_id = self.application.config['campaign_id']
		campaign_id = str(campaign_id)
		config = {
			'created': datetime.datetime.utcnow(),
			'configuration': config
		}
		self.storage['campaigns'][campaign_id] = config

	def get_message_config_tab(self):
		main_window = self.application.main_window
		mailer_tab = main_window.tabs['mailer']
		return mailer_tab.tabs['config']
		mailer_config_tab.objects_save_to_config()

	def get_current_config(self):
		"""
		Get the current configuration options that are managed. This saves the
		settings from the message configuration tab to the standard
		configuration then returns a new dictionary with all of the managed
		settings.

		:return: The current configuration options.
		:rtype: dict
		"""
		app_config = self.application.config
		mailer_config_tab = self.get_message_config_tab()
		mailer_config_tab.objects_save_to_config()
		current_config = dict((key, value) for key, value in app_config.items() if is_managed_key(key))
		return current_config

	def signal_kpc_campaign_set(self, app, old_campaign_id, new_campaign_id):
		dft_config = self.load_default_config()
		app_config = self.application.config
		mailer_config_tab = self.get_message_config_tab()

		if old_campaign_id is not None:
			# switching campaigns
			self.set_campaign_config(self.get_current_config(), old_campaign_id)
			self.save_storage()

		new_campaign_config = self.get_campaign_config(new_campaign_id)
		if new_campaign_config:
			for key in app_config.keys():
				if not is_managed_key(key):
					continue
				if key in new_campaign_config:
					app_config[key] = new_campaign_config[key]
				elif key in dft_config:
					app_config[key] = dft_config[key]
		elif not self.config['transfer_options']:
			for key in app_config.keys():
				if not is_managed_key(key):
					continue
				app_config[key] = dft_config.get(key)

		mailer_config_tab.objects_load_from_config()
