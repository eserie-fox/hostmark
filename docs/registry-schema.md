# Registry schema

## Document

A version-one registry is a JSON object containing exactly these fields, in this canonical order:

| Field | Type | Contract |
| --- | --- | --- |
| `schema_version` | integer | Required and exactly `1`. |
| `dns_suffix` | string | Lower-case ASCII DNS name, no trailing dot/wildcard/IP literal, at least two valid labels, at most 253 characters. |
| `sites` | array of strings | Unique valid site codes; sorted lexicographically in canonical output. |
| `hosts` | array of objects | Host records sorted by `hostname`, then `host_id`, in canonical output. |

A site code is two through six lower-case ASCII letters followed by a positive decimal number, with total length at most
eight. The number starts at 1, so `nc1` and `hk12` are valid while `nc0`, `NC1`, and `nc01` are not. Existing site codes
are append-only under baseline validation.

## Host record

Every host object contains exactly these required fields, including nullable fields, in this order:

| Field | Type | Contract |
| --- | --- | --- |
| `host_id` | string | Canonical lower-case hyphenated UUID, exactly version 4; globally unique and immutable. |
| `hostname` | string | Current canonical short hostname; globally and permanently owned by this UUID. |
| `status` | string | Exactly `active` or `retired`. |
| `registered_at` | string | Strict whole-second UTC RFC 3339 registration timestamp. |
| `previous_hostnames` | array of strings | Oldest-to-newest names formerly current for this same UUID; append-only and never sorted. |
| `retirement` | object or null | Null while active; exact retirement object while retired. |
| `notes` | string or null | Null or a non-whitespace non-empty string. |

A hostname is at most 15 characters, lower-case ASCII letters/digits separated by single hyphens, with no dot,
underscore, whitespace, Unicode, edge hyphen, or consecutive hyphen. It begins with a site code from `sites` followed by
`-`. A numeric suffix is not required, so `nc1-orange` is valid.

Current and historical hostnames are globally unique across all records. A current name cannot also occur in its own
history. Existing history must remain an exact prefix during baseline comparison. A rename appends the prior current name
before installing the new current name.

## Retirement object

A retirement object contains exactly these fields, in this order:

| Field | Type | Contract |
| --- | --- | --- |
| `retired_at` | string | Strict UTC timestamp, not earlier than `registered_at`; immutable after retirement. |
| `reason` | string | Non-whitespace human-readable text; later correction is allowed. |
| `replacement_host_id` | string or null | Optional existing UUID; not self; graph must be acyclic. |

A new replacement assignment must point to an active candidate record. It is historical metadata, not hostname
inheritance or automated migration. Once non-null, it cannot be cleared or changed. A replacement may itself be retired
in a later snapshot.

## Strict timestamp and JSON rules

Timestamps use only `YYYY-MM-DDTHH:MM:SSZ`: UTC `Z`, whole seconds, no local offset, fractional seconds, or naive form.

The decoder requires UTF-8 without a BOM and rejects duplicate object keys at every nesting depth. Unknown and missing
fields, non-standard constants such as `NaN`, invalid types, and schema versions other than 1 are errors.

Canonical bytes use LF on every platform, two-space indentation, no trailing whitespace, direct UTF-8 Unicode, fixed
field order, sorted sites, sorted hosts, preserved history order, and exactly one final newline. A semantically valid but
differently formatted file can be formatted; an invalid file cannot.

## Snapshot and baseline validation

Snapshot validation also checks unique host IDs/sites/names, site membership, lifecycle/retirement consistency,
retirement chronology, replacement existence/self-reference/cycles, and all text constraints.

`registry validate --against` rejects host deletion or identity replacement, registration-time rewrites, retired-to-active
transitions, name transfer, history deletion/reordering, retired hostname/time changes, non-null replacement changes,
site removal, schema changes, and replacement cycles. Active notes, correct renames, retirement, new records, and site
additions are allowed. Retired notes/reason corrections and one null-to-valid replacement assignment are allowed. A DNS
suffix change is accepted with a prominent warning because it changes every computed FQDN.
