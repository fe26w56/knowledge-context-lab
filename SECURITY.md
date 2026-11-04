# Security

This project is an offline evaluation library. It is not an authentication service, secrets manager, hosted database, or production availability implementation.

`actor` is a caller-supplied identity used by the local synthetic tests. The retrieval API does not authenticate that identity. Applications must authenticate and authorize callers before constructing a request, enforce their own tenant boundary, and avoid exposing private source metadata through logs or diagnostics.

Please do not report real personal data or secret values in an issue. Remove credentials from logs and fixtures, then describe the behavior with synthetic identifiers. For a suspected security problem, contact the repository owner privately before publishing details; use GitHub private vulnerability reporting when available. If that option is unavailable, contact the maintainer through their public profile without including exploit details or secret values in a public issue.

The fault experiments use injected failures against isolated local SQLite files. Passing them does not establish HTTP, D1, disk-failure, or production recovery guarantees.

