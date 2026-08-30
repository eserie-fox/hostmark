# Registry data boundary

`hosts.example.json` is synthetic documentation and test data using reserved example domains. It is not authoritative,
and this source-code directory is not the v0.2 inventory layout.

Create the real private source of truth in a separate marked repository:

```bash
hostmark repo init \
  --dns-suffix <real-node-suffix> \
  --site nc1
```

That repository contains root `HOSTMARK_REPOSITORY` and `hosts.json`. Review and commit both manually; Hostmark does not
stage, commit, configure a remote, or push. The source distribution excludes this entire example directory, and artifact
checks also reject live marker or inventory data. See [the repository guide](../docs/repository.md), including the manual
v0.1 `registry/hosts.json` migration and continued direct-path override support.

This registry owns host UUIDs, canonical short hostnames, site codes, and lifecycle history. Service DNS, Cloudflare
CNAMEs, IP/MAC/DHCP data, credentials, runtime reachability, and monitoring remain outside it.
