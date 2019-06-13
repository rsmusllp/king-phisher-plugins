# Request Redirect
This plugin provides a GUI editor for request redirect configurations used on
the King Phisher server. **This plugin requires that the server side
`request_redirect` plugin be installed and enabled as well.**

## Request Redirect Configuration Entries
Configuration entries are composed of the following fields:

* **Target:** The target field is the destination that the HTTP client will be
  redirected to if the request redirect configuration entry matches the request.
* **Permanent:** Whether a 301 (`Moved Permanently`) HTTP response should be
  issued or a 302 (`Found`) HTTP response when an entry matches an incoming
  request.
* **Type:** The type of the entry. This field's value must be either `Rule` or
  `Source` and determines how the entry text should be applied to the incoming
  request for the purposes of matching.
* **Text:** The text used for evaluating based on the entry's type to determine
  if an incoming requests matches or not.

### Entry Types
Configuration entries come in one of the following types:

* **Rule:** Rules are expressions using the [rule-engine][1] to match requests
  based on characteristics. Requests which match a rule (causing it to evaluate)
  will be redirected to the specified target. See the rule-engine [syntax][2]
  documentation for more information.

* **Source:** Sources are IP networks in CIDR notation that are used to match
  the source address of a request. If the source address of the request is in
  the specified CIDR range, it will be redirected to the specified target.

#### Rule Symbols
The following symbols are available for use in configuration entries to match
incoming requests.

| Symbol       | Type   | Description                                             |
| ------------ | ------ | ------------------------------------------------------- |
| `accept`     | STRING | The value of the `Accept` header, if present            |
| `dst_addr`   | STRING | The IP address on the server which received the request |
| `dst_port`   | FLOAT  | The port on the server which received the request       |
| `path`       | STRING | The resource portion of the request                     |
| `src_addr`   | STRING | The IP address that the request is from                 |
| `src_port`   | FLOAT  | The port that the request is from                       |
| `user_agent` | STRING | The value of the `User-Agent` header, if present        |
| `verb`       | STRING | The HTTP verb of the request                            |
| `vhost`      | STRING | The value of the `Host` header, if present              |

#### Example Rules

Match Internet Explore by applying a regex to the User-Agent:

`user_agent =~~ 'MSIE \d+\.\d+; Windows NT'`

Match GET requests for `robots.txt`:

`path == '/robots.txt' and verb == 'GET'`

### Configuration Exceptions
To create an exception, create a rule earlier in the chain (with a lower index
number) with an empty target. Configuration entries are evaluated in order, just
like firewall entries, and the first one to match is the target that will be used.
An empty target an exception and will cause the matching to stop, and the
request will be handled by the King Phisher server.

[1]: https://zerosteiner.github.io/rule-engine/index.html
[2]: https://zerosteiner.github.io/rule-engine/syntax.html
