These localhost-only, self-signed TLS fixtures exercise certificate rejection
and explicit trust recovery. The private key is public test data and must never
be used by an application or production server. The certificate SAN covers
localhost and 127.0.0.1. No user certificate or credential is included.
