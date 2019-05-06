# Request Redirect
This plugin provides a GUI editor for request redirect configurations used on
the King Phisher server. **This plugin requires that the server side
`request_redirect` plugin be installed and enabled as well.**

## Request Redirect Configuration Entries
Configuration entries come in one of the following types:

* **Rule:** Rules are expressions using the [rule-engine][1] to match requests
  based on characteristics. Requests which match a rule (causing it to evaluate)
  will be redirected to the specified target. See the rule-engine [syntax][2]
  documentation for more information.

* **Source:** Sources are IP networks in CIDR notation that are used to match
  the source address of a request. If the source address of the request is in
  the specified CIDR range, it will be redirected to the specified target.

### Rule Symbols
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

### Example Rules

Match Internet Explore by applying a regex to the User-Agent:

`user_agent =~~ 'MSIE \d+\.\d+; Windows NT'`

Match GET requests for `robost.txt`:

`path == 'robots.txt' and verb == 'GET'`

### Configuration Exceptions
To create an exception, create a rule earlier in the chain (with a lower index
number) with an empty target. Configuration entries are evaluated in order, just
like firewall entries, and the first one to match is the target that will be used.
An empty target an exception and will cause the matching to stop, and the
request will be handled by the King Phisher server.

[1]: https://zerosteiner.github.io/rule-engine/index.html
[2]: https://zerosteiner.github.io/rule-engine/syntax.html