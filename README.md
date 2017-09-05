![alt text](https://github.com/securestate/king-phisher/raw/master/data/king-phisher-logo.png "King Phisher")
<!-- generated at: 2017-09-05 15:32:12 -->
# King Phisher Plugins
Plugins to extend the [King Phisher][king-phisher-repo] Phishing Campaign
Toolkit. For more information regarding King Phisher, see the project's
[wiki page][king-phisher-wiki].

## Client Plugins
| Name                                      | Description       |
|:------------------------------------------|:------------------|
| [URI Spoof Generator](/client/uri_spoof_generator.py) | Exports a redirect page which allows URI spoofing in the address bar of the target's browser |
| [Office 2007+ Document Metadata Remover](/client/office_metadata_remover.py) | Remove metadata from Microsoft Office 2007+ file types. These files types generally use the extension docx, pptx, xlsx etc. If the attachment file is not an Office 2007+ file, this plugin does not modify it or block the sending operation. |
| [Upload KPM](/client/kpm_export_on_send.py) | Saves a KPM file to the King Phisher server when sending messages. The user must have write permissions to the specified directories. Both the "Local Directory" and "Remote Directory" options can use the variables that are available for use in message templates. |
| [Spell Check](/client/spell_check.py) | Add spell check capabilities to the message editor. This requires GtkSpell to be available with the correct Python GObject Introspection bindings. On Ubuntu and Debian based systems, this is provided by the 'gir1.2-gtkspell3-3.0' package.<br /><br />After being loaded, the language can be changed from the default of en_US via the context menu (available when right clicking in the text view). |
| [Phishery DOCX URL Injector](/client/phishery_docx.py) | Use Phishery to inject Word Document Template URLs into DOCX files. This can be used in conjunction with a server page that requires Basic Authentication to collect Windows credentials. Note that for HTTPS URLs, the King Phisher server needs to be configured with a proper, trusted SSL certificate for the user to be presented with the basic authentication prompt.<br /><br />Phishery homepage: https://github.com/ryhanson/phishery |
| [Generate PDF](/client/pdf_generator.py) | Generates a PDF file with a link which includes the campaign URL with the individual message_id required to track individual visits to a website. Visit https://github.com/y4utj4/pdf_generator for example template files to use with this plugin. |
| [File Logging](/client/file_logging.py) | Write the client's logs to a file in the users data directory. Additionally if an unhandled exception occurs, the details will be written to a dedicated directory. |
| [Blink(1) Notifications](/client/blink1.py) | A plugin which will flash a Blink(1) peripheral based on campaign events such as when a new visit is received or new credentials have been submitted. |
| [Clockwork SMS](/client/clockwork_sms.py) | Send SMS messages using the Clockwork SMS API's email gateway. While enabled, this plugin will automatically update phone numbers into email addresses for sending using the service. |
| [TOTP Self Enrollment](/client/totp_enrollment.py) | This plugin allows users to manage the two factor authentication settings on their account. This includes setting a new and removing an existing TOTP secret. The two factor authentication used by King Phisher is compatible with free mobile applications such as Google Authenticator. |
| [DMARC Check](/client/dmarc.py) | This plugin adds another safety check to the message precheck routines to verify that if DMARC exists the message will not be quarentined or rejected. If no DMARC policy is present, the policy is set to none or the percentage is set to 0, the message sending operation will proceed. |
| [Save KPM On Exit](/client/kpm_export_on_exit.py) | Prompt to save the message data as a KPM file when King Phisher exits. |
| [Hello World!](/client/hello_world.py) | A 'hello world' plugin to serve as a basic template and demonstration. This plugin will display a message box when King Phisher exits. |
| [Domain Validator](/client/domain_check.py) | Checks to see if a domain can be resolved. Good for email spoofing and bypassing some spam filters. |
| [SFTP Client](/client/sftp_client.py) | Secure File Transfer Protocol Client that can be used to upload, download, create, and delete local and remote files on the King Phisher Server.<br /><br />The editor allows you edit files on remote or local system. It is primarily designed for the use of editing remote web pages on the King Phisher Server. |

## Server Plugins
| Name                                      | Description       |
|:------------------------------------------|:------------------|
| [Pushbullet Notifications](/server/pushbullet_notifications.py) | A plugin that uses Pushbullet's API to send push notifications on new website visits and submitted credentials. |
| [IFTTT Campaign Success Notification](/server/ifttt_on_campaign_success.py) | A plugin that will publish an event to a specified IFTTT Maker channel when a campaign has been deemed 'successful'. |
| [XMPP Notifications](/server/xmpp_notifications.py) | A plugin which pushes notifications regarding the King Phisher server to a specified XMPP server. |
| [Hello World!](/server/hello_world.py) | A 'hello world' plugin to serve as a basic template and demonstration. This plugin will log simple messages to show that it is functioning. |

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
King Phisher Plugins are released under the BSD 3-clause license, for more
details see the [LICENSE][license-file] file.

[king-phisher-repo]: https://github.com/securestate/king-phisher
[king-phisher-wiki]: https://github.com/securestate/king-phisher/wiki
[license-file]: /LICENSE