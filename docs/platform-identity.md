# Platform identity storage

Each file contains exactly one canonical UUIDv4 and LF: `<uuid>\n`. Host IDs identify OS instances; they are not
authentication secrets.

## Paths

| Platform | Recommended system scope | Explicit user scope |
| --- | --- | --- |
| Linux | `/etc/hostmark/host-id` | `$XDG_CONFIG_HOME/hostmark/host-id`, or `~/.config/hostmark/host-id` |
| macOS | `/Library/Application Support/Hostmark/host-id` | `~/Library/Application Support/Hostmark/host-id` |
| Windows | `%ProgramData%\Hostmark\host-id` | `%LOCALAPPDATA%\Hostmark\host-id` |

If Windows lacks `ProgramData`, Hostmark uses `~/ProgramData/Hostmark/host-id`; if it lacks `LOCALAPPDATA`, it uses
`~/AppData/Local/Hostmark/host-id`. These distinct home-based fallbacks keep discovery deterministic.

On Linux, `XDG_CONFIG_HOME` is used only when it is an absolute path. A missing, empty, or relative value falls back to
`~/.config/hostmark/host-id`; a relative value is never interpreted from the current working directory.

## Discovery and conflicts

Every identity-reading command checks both paths. Neither means uninitialized; exactly one is selected; two are always a
conflict, even if both contain the same UUID. Hostmark never silently prioritizes a scope. Remove the unintended duplicate
manually after verifying which identity should survive. Malformed bytes are an error.

## Initialization and privilege behavior

`hostmark identity init` defaults to system scope, creates parent directories, uses exclusive file creation, flushes and
fsyncs the generated UUID, and refuses any existing identity in either scope. It never falls back automatically and has
no `--force` or reset operation.

On Linux and macOS, system scope requires root. Before re-execution, `--sudo` resolves and checks the system identity and
the invoking user's identity path. It carries that user path as one argv item rather than relying on sudo-preserved
`HOME` or `XDG_CONFIG_HOME`, then the privileged process checks both paths again immediately before exclusive creation.
An identity that appears during elevation therefore blocks initialization. Sudo availability is checked first, and no
shell command is constructed. Without `--sudo`, Hostmark prints an actionable retry. Choose `--scope user` explicitly
when system storage is inappropriate; `--sudo` is invalid with user scope.

Windows does not use Unix sudo. Run an elevated terminal when ProgramData is not writable. Version 1 relies on inherited
Windows ACLs and adds no ACL library.

There is no automatic startup service. Identity is read only when a command runs. Never include a host-ID file in a VM
template, golden image, or generic installer image.
