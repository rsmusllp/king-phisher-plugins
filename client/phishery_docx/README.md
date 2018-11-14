## HTTP URL
The Jinja variable `{{ url.webserver }}` can be used for an HTTP URL to track
when documents are opened.

Note that to only track opened documents, **do not** put a URL link into the
phishing email to the landing page (`{{ url.webserver }}`). This will ensure
that visits are only registered for instance where the document is opened.

## HTTPS URL
The Jinja variable `{{ url.webserver }}` can be used for an HTTPS landing page
that requires basic authentication.

Note that for HTTPS URLs, the King Phisher server needs to be configured with a
proper, trusted SSL certificate for the user to be presented with the basic
authentication prompt. The [LetsEncrypt project](https://letsencrypt.org/)
project can be used for this purpose.

## FILE URL
Utilizing the `file://yourtargetserver/somepath` URL format will capture SMB
credentials.

Note that King Phisher does not support SMB, and utilization of SMB requires
that a separate capture/sniffer application such as Metasploit's
`auxiliary/server/capture/smb` module will have to be used to capture NTLM
hashes. The plugin and King Phisher will only support injecting the URL path
into the document.
