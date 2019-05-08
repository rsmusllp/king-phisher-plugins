This plugin wil take an HTML attachment and turn it into a PDF attachment when
sending the email to a target.

Inline CSS style is respected during generation of the PDF. You can also specify
multiple `css_stylesheets` in the plugin options. **Note:** Any inline CSS will
have priority over settings in the CSS stylesheet.

When working on and rendering the HTML file, it is recommend to use the message
editor and preview tabs in the King Phisher client. This will cause any Jinja
tags to be properly rendered. Users may then select the "Create PDF Preview"
option from the Tools menu to verify the PDF format is correct. **Remember to
switch the editor bach over to the email's message template when done.**

## HTML

### Elements
Many of the HTML elements are implemented in CSS through the default HTML
(User-Agent) stylesheet. Some of these elements will need special treatment and
consideration.

Special Consideration Elements:

* The `<base>` element, if present, determines the base for relatives URLs.
* CSS Stylesheets can be embedded in `<style>` elements.
* `<img>`, `<embed>`, and `<object>` elements accept images either in raster
  formats supported by `GdkPixbuf` (including PNG, JPEG, GIF, ...) or in SVG
  format with CairoSVG. SVG images are not rasterized but rendered as vectors in
  the PDF output.
* Only utilize absolute paths for links and images.

Formatting and notes with elements:

* Headers `<h1>`, `<h2>` will be used to create the outlines and bookmarks in
  the PDF document.
* You can link to internal parts of the PDF with anchors, e.g. `<a href="#pdf">`.

Additional notes on the PDF Generation can be found in the weasyprint
[HTML documentation][1].

### Jinja Variables
The PDF plugin will parse any King Phisher client [Jinja variables][2] in the
HTML prior to rendering the PDF content.

When generating links in the email message for tracking, remember to use
`<a href="{{ url.webserver }}">Your Mask</a>` so each link is tracked and tied
to its respective target.

#### Additional Notes
This plugin utilizes `weasyprint` version 47. The developer recommends only
using this version in case the API changes.

##### Developer notes
This plugin defines `base_url` for the `weasyprint` HTML class which is
undefined in its documentation, but is auto generated when passed a file object.
As this plugin parses the HTML file for King Phisher client Jinja variables
prior to passing in a string to the `weasyprint` HTML object, the plugin needs
to maintain access to this variable so images and other objects or loaded and
PDF correctly.

[1]: https://weasyprint.readthedocs.io/en/latest/features.html
[2]: https://github.com/securestate/king-phisher/wiki/Templates#message-templates
