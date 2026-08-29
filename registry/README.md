# Registry data boundary

`hosts.example.json` is synthetic documentation and test data using reserved example domains. It is not authoritative.

Create the real private source of truth as `registry/hosts.json`:

```bash
hostmark registry init \
  --registry registry/hosts.json \
  --dns-suffix <real-node-suffix> \
  --site nc1
```

The real file is intended to be reviewed and committed in this private Git repository; it is deliberately not ignored.
The entire `registry/` directory is excluded from Python wheels and source distributions, and CI verifies that boundary.

This registry owns host UUIDs, canonical short hostnames, site codes, and lifecycle history. Service DNS, Cloudflare
CNAMEs, IP/MAC/DHCP data, credentials, runtime reachability, and monitoring remain outside it.
