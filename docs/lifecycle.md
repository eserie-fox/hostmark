# Identity lifecycle

## Active and retired

`active` means the identity still exists for administrative purposes. A powered-down, paused, temporarily unused,
offline, or unreachable machine remains active. `retired` means that identity has permanently ended. Retirement is
terminal: there is no deletion or unretirement operation.

## Same identity, new hostname

Rename an existing active UUID when the same logical OS identity receives a new canonical name. If `A` becomes `B`, the
record keeps its UUID and registration time, changes `hostname` to `B`, and appends `A` to `previous_hostnames`. The list
is chronological and append-only. It records only names that were canonical for this UUID in this registry—not DNS
aliases, vendor labels, service names, or arbitrary pre-adoption names.

All current and previous names stay reserved to their original UUID forever. A multi-step edit may append several names,
but the baseline current name must be the first new history entry.

Use the registry as expected state during a rename:

1. Change the registry hostname, using `--dry-run` first when useful.
2. Commit and review the registry update.
3. Run `hostmark check` on the machine and confirm it reports the expected mismatch.
4. Manually change the operating-system hostname.
5. Run `hostmark check` again and require success.

Changing the operating-system hostname first reverses the source-of-truth workflow and should be avoided. Hostmark only
reports drift; it never remediates the OS name.

## New identity replacing an ended one

A rebuilt VM, clone, replacement machine, or independently reinstalled identity normally receives a new UUID and a new
hostname. Retire the old UUID and optionally set its `replacement_host_id` to the active successor. This is one-way
historical metadata. It does not imply hostname inheritance, identical hardware or configuration, DNS changes, or service
migration. Use null when there is no clear one-to-one successor.

The new identity may never reuse the old current or historical hostname. Replacement chains are allowed but cycles are
not. Reverse “replaces” relationships are derived when displaying a record and are not stored.

## Reinstall, restore, and clone decisions

- A deliberate restore of the same logical identity may manually restore the old host-ID file after confirming the old
  identity remains active and the new installation is not simultaneously using another ID. This is an advanced operator
  recovery, not a CLI reset command.
- A reinstall treated as a new logical instance generates a new ID, registers a new hostname, and retires the old ID.
- A clone is always a new identity. Remove any template-baked host-ID before cloning and run `identity init` independently
  on the clone.
- Never bake `host-id` into a VM template or generic image.

Tombstones retain ownership and explain history. They must remain in Git even after hardware, disks, and service
configuration are gone.
