![alt text](https://github.com/securestate/king-phisher/raw/master/data/king-phisher-logo.png "King Phisher")
<!-- generated at: 2017-03-10 17:02:38 -->
# King Phisher Plugins
Plugins to extend the [King Phisher][king-phisher-repo] Phishing Campaign
Toolkit. For more information regarding King Phisher, see the project's
[wiki page][king-phisher-wiki].

## Client Plugins
| Name                                      | Description       |
|:------------------------------------------|:------------------|
| [Spell Check][c_spell_check] | Add spell check capabilities to the message editor. This requires GtkSpell to be available with the correct Python GObject Introspection bindings. On Ubuntu and Debian based systems, this is provided by the 'gir1.2-gtkspell3-3.0' package.<br /><br />After being loaded, the language can be changed from the default of en_US via the context menu (available when right clicking in the text view). |
| [Clockwork SMS][c_clockwork_sms] | Send SMS messages using the Clockwork SMS API's email gateway. While enabled, this plugin will automatically update phone numbers into email addresses for sending using the service. |
| [Upload KPM][c_kpm_export_on_send] | Saves a KPM file to the King Phisher server when sending messages. The user must have write permissions to the specified directories. Both the "Local Directory" and "Remote Directory" options can use the variables that are available for use in message templates. |
| [Generate PDF][c_pdf_generator] | Generates a PDF file with a link which includes the campaign URL with the individual message_id required to track individual visits to a website. Visit https://github.com/y4utj4/pdf_generator for example template files to use with this plugin. |
| [TOTP Self Enrollment][c_totp_enrollment] | This plugin allows users to manager the two factor authentication settings on their account. This includes setting a new and removing an existing TOTP secret. The two factor authentication used by King Phisher is compatible with free mobile applications such as Google Authenticator. |
| [Hello World!][c_hello_world] | A 'hello world' plugin to serve as a basic template and demonstration. This plugin will display a message box when King Phisher exits. |
| [Save KPM On Exit][c_kpm_export_on_exit] | Prompt to save the message data as a KPM file when King Phisher exits. |
| [Blink(1) Notifications][c_blink1] | A plugin which will flash a Blink(1) peripheral based on campaign events such as when a new visit is received or new credentials have been submitted. |
| [URI Spoof Generator][c_uri_spoof_generator] | Exports a redirect page which allows URI spoofing in the address bar of the target's browser |
| [SFTP Client][c_sftp_client] | Secure File Transfer Protocol Client that can be used to upload, download, create, and delete local and remote files on the King Phisher Server. |
| [File Logging][c_file_logging] | Write the client's logs to a file in the users data directory. Additionally if an unhandled exception occurs, the details will be written to a dedicated directory. |

## Server Plugins
| Name                                      | Description       |
|:------------------------------------------|:------------------|
| [Pushbullet Notifications][s_pushbullet_notifications] | A plugin that uses Pushbullet's API to send push notifications on new website visits and submitted credentials. |
| [Hello World!][s_hello_world] | A 'hello world' plugin to serve as a basic template and demonstration. This plugin will log simple messages to show that it is functioning. |
| [XMPP Notifications][s_xmpp_notifications] | A plugin which pushes notifications regarding the King Phisher server to a specified XMPP server. |
| [IFTTT Campaign Success Notification][s_ifttt_on_campaign_success] | A plugin that will publish an event to a specified IFTTT Maker channel when a campaign has been deemed 'successful'. |

## Plugin Installation
### Client Plugin Installation
Client plugins can be placed in the `$HOME/.config/king-phisher/plugins`
directory, then loaded and enabled with the plugin manager.

### Server Plugin Installation
Server plugins can be placed in the `data/server/king_phisher/plugins`
directory of the King Phisher installation. Additional search paths can be
defined using `plugin_directories` in the server's configuration file. After
being copied into the necessary directory, the server's configuration file
needs to be updated to enable the plugin.

## License
King Phisher Templates are released under the BSD 3-clause license, for more
details see the [LICENSE][license-file] file.

[king-phisher-repo]: https://github.com/securestate/king-phisher
[king-phisher-wiki]: https://github.com/securestate/king-phisher/wiki
[license-file]: https://github.com/securestate/king-phisher-templates/blob/master/LICENSE
[c_spell_check]: https://github.com/securestate/king-phisher-plugins/blob/master/client/spell_check.py
[c_clockwork_sms]: https://github.com/securestate/king-phisher-plugins/blob/master/client/clockwork_sms.py
[c_kpm_export_on_send]: https://github.com/securestate/king-phisher-plugins/blob/master/client/kpm_export_on_send.py
[c_pdf_generator]: https://github.com/securestate/king-phisher-plugins/blob/master/client/pdf_generator.py
[c_totp_enrollment]: https://github.com/securestate/king-phisher-plugins/blob/master/client/totp_enrollment.py
[c_hello_world]: https://github.com/securestate/king-phisher-plugins/blob/master/client/hello_world.py
[c_kpm_export_on_exit]: https://github.com/securestate/king-phisher-plugins/blob/master/client/kpm_export_on_exit.py
[c_blink1]: https://github.com/securestate/king-phisher-plugins/blob/master/client/blink1.py
[c_uri_spoof_generator]: https://github.com/securestate/king-phisher-plugins/blob/master/client/uri_spoof_generator.py
[c_sftp_client]: https://github.com/securestate/king-phisher-plugins/blob/master/client/sftp_client.py
[c_file_logging]: https://github.com/securestate/king-phisher-plugins/blob/master/client/file_logging.py
[s_pushbullet_notifications]: https://github.com/securestate/king-phisher-plugins/blob/master/server/pushbullet_notifications.py
[s_hello_world]: https://github.com/securestate/king-phisher-plugins/blob/master/server/hello_world.py
[s_xmpp_notifications]: https://github.com/securestate/king-phisher-plugins/blob/master/server/xmpp_notifications.py
[s_ifttt_on_campaign_success]: https://github.com/securestate/king-phisher-plugins/blob/master/server/ifttt_on_campaign_success.py
