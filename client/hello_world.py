import king_phisher.client.plugins as plugins
import king_phisher.client.gui_utilities as gui_utilities

# this is the main plugin class, it is necessary to inherit from plugins.ClientPlugin
class Plugin(plugins.ClientPlugin):
    authors = ['Spencer McIntyre']  # the plugins author
    title = 'Hello World!'          # the title of the plugin to be shown to users
    description = """
    A 'hello world' plugin to serve as a basic template and demonstration. This
    plugin will display a message box when King Phisher exits.
    """                             # a description of the plugin to be shown to users
    homepage = 'https://github.com/securestate/king-phisher-plugins'  # an optional home page
    options = [  # specify options which can be configured through the GUI
        plugins.ClientOptionString(
            'name',                               # the name of the option as it will appear in the configuration
            'The name to which to say goodbye.',  # the description of the option as shown to users
            default='Alice Liddle',               # a default value for the option
            display_name='Your Name'              # a name of the option as shown to users
        )
        plugins.ClientOptionBoolean(
            'validiction',
            'Whether or not this plugin say good bye.',
            default=True,
            display_name='Say Good Bye'
        ),
        plugins.ClientOptionInteger(
            'some_number',
            'An example number option.',
            default=1337,
            display_name='A Number'
        ),
        plugins.ClientOptionPort(
            'tcp_port',
            'The TCP port to connect to.',
            default=80,
            display_name='Connection Port'
        )
    ]
    req_min_version = '1.4.0'  # (optional) specify the required minimum version of king phisher
    version = '1.0'            # (optional) specify this plugin's version
    # this is the primary plugin entry point which is executed when the plugin is enabled
    def initialize(self):
        print('Hello World!')
        self.signal_connect('exit', self.signal_exit)
        # it is necessary to return True to indicate that the initialization was successful
        # this allows the plugin to check its options and return false to indicate a failure
        return True

    # this is a cleanup method to allow the plugin to close any open resources
    def finalize(self):
        print('Good Bye World!')

    # the plugin connects this handler to the applications 'exit' signal
    def signal_exit(self, app):
        # check the 'validiction' option in the configuration
        if not self.config['validiction']:
            return
        gui_utilities.show_dialog_info(
            "Good bye {0}!".format(self.config['name']),
            app.get_active_window()
        )
