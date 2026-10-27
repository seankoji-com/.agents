# Route a pinned skill request

Use the text after the skill mention as the request. The pinned `plugin.json` owns
operations, routes, picker order, standalone flags and any default operation.
Remove declared standalone flags for routing, preserve the original request for
execution, and select the first route matching the whole request. With no match
or a bare invocation, use the declared default when present. Otherwise ask for
the missing operation or fact through the native picker, recommended option first.
This contract grants no extra authority and never selects another installation.
