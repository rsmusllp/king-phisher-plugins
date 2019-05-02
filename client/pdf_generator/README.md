# PDF Generator
Will take the HTML attachment and turn it into a PDF attachment when sending
the email to a target.

Inline `css` style is respected during generation of the pdf.
You can also specify multiple `css stylesheets` in the plugin options.
**Note** Any inline css will have priority over setting in the css stylesheet.

When working on and rending the html file it is recommend to use the message
editor and preview tabs in the King Phisher client. This will allow any
Jinja tags are properly rendered. Then use the Create PDF preview option from the
Tools in the menu bar to verify the PDF format is meeting your needs.
**Remember to switch the editor bach over to your email message when done.**

## HTML

### Elements
Many of HTML elements are implemented in CSS through the default HTML (User-Agent)
stylesheet. Some of these elements will need special treatment and consideration.

Special Consideration Elements:
* The `<base>` element, if present, determines the base for relatives URLs.
* CSS Stylesheets can be embedded in `<style>` elements.
* `<img>`, `<embed>`, or `<object>` elements accept images either in raster formats
  supported by `GdkPixbuf` (including PNG, JPEG, GIFF, ...) or in SVG with CairoSVG.
  SVG images are not rasterized but rendered as vectors in the PDF output.
* Only utilize absolute path for links and images

Formatting and notes with elements:
* headers `<h1>`, `<h2>` will be used to create the outlines and bookmarks in the PDF document.
* You can link to internal parts of the PDF with `<a href="#pdf">`

Additional notes on the PDF Generation can be found at:
[weasyprint HTML documentation](https://weasyprint.readthedocs.io/en/latest/features.html)

### Jinja Variables
The PDF plugin will parse any
[client King Phisher jinja variables](https://github.com/securestate/king-phisher/wiki/Templates#message-templates)
prior to rendering into PDF format.

Just link generating links in the email message for tracking remember to 
use `<a href="{{ url.webserver }}">Your Mask</a>` so each link is tracked and tied to each target.

#### Additional Notes
This plugin utilizes `weasyprint` version 47. The developer recommends only using this version
incase the API changes. 

##### Developer notes
This plugin defines `base_url` for `weasyprint` HTML class which is undefined in its documentation,
but is auto generated when passed a file object. As this plugin parses the html file for client
King Phisher variables prior to passing in a string to `weasyprint` HTML object the plugin
needs to maintain access to this variable so images and other objects or loaded and PDF correctly.
