# Inventory repository

## Canonical layout and marker

A Hostmark inventory repository may have any directory name. Its root is identified only by this layout:

```text
<repository-root>/
├── .git                 # directory or linked-worktree file
├── .gitattributes
├── HOSTMARK_REPOSITORY
└── hosts.json
```

`HOSTMARK_REPOSITORY` is a readable regular file containing exactly zero bytes. It is not configuration and carries no
version. `.gitattributes` is a readable regular file with these exact LF bytes:

```gitattributes
/HOSTMARK_REPOSITORY -text
/hosts.json text eol=lf
```

The attributes keep the marker byte-stable and force canonical LF registry checkouts even when Git is configured with
`core.autocrlf=true`. `hosts.json` is the existing schema-version-one canonical registry. All three root files must be
tracked. The Hostmark source checkout intentionally has none of them at its root and is not an inventory repository.

## Defaults and discovery

The per-user defaults are:

| Platform | Repository root |
| --- | --- |
| Linux | `${XDG_DATA_HOME:-~/.local/share}/hostmark/repo` |
| macOS | `~/Library/Application Support/Hostmark/repo` |
| Windows | `%LOCALAPPDATA%\Hostmark\repo` |

Linux uses `XDG_DATA_HOME` only when it is nonempty and POSIX-absolute. Windows falls back to
`~/AppData/Local/Hostmark/repo` when `LOCALAPPDATA` is unavailable.

Repository resolution uses `--repo`, then `HOSTMARK_REPO`, then the nearest ancestor containing the exact marker, then
the platform default. Discovery checks only the current directory and its parents. An invalid nearer marker is an error;
Hostmark does not skip it or scan child directories.

Registry commands preserve file-level overrides. Their order is `--registry`, `HOSTMARK_REGISTRY`, `HOSTMARK_REPO`, the
nearest marked ancestor, then the initialized platform default. Repository-derived paths always end in root
`hosts.json`. Direct file overrides require no marker and remain suitable for CI or noncanonical legacy locations.

## Initialize and publish manually

```bash
hostmark repo init \
  --dns-suffix node.infra.example.com \
  --site nc1
hostmark repo path
# Change into the printed repository directory, then run:
git add .gitattributes HOSTMARK_REPOSITORY hosts.json
git commit -m "Initialize hostmark repository"
git remote add origin <remote-url>
git push -u origin main
```

Initialization accepts an absent or empty target, validates inputs first, requires system Git, initializes an unborn
`main` branch, and creates only canonical attributes, the marker, and the empty registry. It never stages, commits,
configures identity or a remote, pushes, creates a host UUID, or registers the machine. The repository is deliberately
not sync-ready until the three files are staged and committed and an `origin` upstream is configured.

## Clone and synchronize

```bash
hostmark identity init --sudo
hostmark repo sync --remote <remote-url>
hostmark registry register <hostname>
git add hosts.json
git commit -m "Register host"
git push
hostmark check

# Later:
hostmark repo sync && hostmark check
```

An administrator may pre-register a new machine only with the UUID created by `identity init` on that machine.

An absent or empty target requires `--remote` and is cloned. An existing repository must have exact canonical
attributes and marker bytes, be the exact Git worktree root, track an `origin/*` branch, contain all three required files
as stage-zero index entries, and have no tracked changes. A branch tracking `backup/*` or any other remote is rejected.
Unrelated untracked files do not block synchronization, but untracked attributes, marker, or registry files never qualify
an unrelated Git repository as an inventory. A supplied `--remote` must exactly match `origin`; Hostmark never changes
the remote or upstream.

Hostmark uses GitPython as a typed interface while retaining the system Git executable. System credential helpers, the
SSH agent/configuration, and known-hosts behavior remain authoritative. Hostmark disables terminal credential prompts;
SSH remotes use BatchMode and `StrictHostKeyChecking=accept-new`.

Synchronization pulls the tracked origin branch with fast-forward-only semantics. It never stashes, resets, cleans,
checks out, rebases, commits, pushes, changes remotes, or repairs divergence. After clone or pull, Hostmark rechecks the
tracked files and strictly validates the attributes, marker, and canonical registry. If Git succeeds but registry
validation fails, exit code 8 is retained; the Git result remains visible and Hostmark does not roll back or rewrite it.

No other command synchronizes implicitly. In particular, `hostmark check` is local and deterministic.

## Migrating a v0.1 layout

Marker discovery applies only to the v0.2 root layout. For an earlier repository containing `registry/hosts.json`:

1. Move `registry/hosts.json` to root `hosts.json`.
2. Create root `.gitattributes` with the exact canonical contents above.
3. Create an empty root `HOSTMARK_REPOSITORY`.
4. Run `hostmark registry validate --registry hosts.json`.
5. Commit `.gitattributes`, the move, and the marker manually.

Hostmark never performs this migration automatically. A repository that stays on the old layout remains usable through
`--registry /old/path/registry/hosts.json` or `HOSTMARK_REGISTRY=/old/path/registry/hosts.json`.

## Inventory-repository CI

CI for the separate private inventory repository is opt-in; `repo init` does not generate a workflow. Install Hostmark
from FoxPI using that repository's protected environment or repository secrets, then run snapshot validation for every
candidate `hosts.json`. On pull requests, extract the exact base-branch `hosts.json` and pass it through `--against`; on
direct main pushes, use the previous main commit in the same way. Snapshot validation alone cannot detect a deleted
tombstone or rewritten history, so append-only ownership and lifecycle enforcement requires the baseline comparison.

Keep FoxPI usernames/passwords in GitHub secrets and pass only the corresponding environment variables to the install
step. The inventory workflow should never print credentials, mutate `hosts.json`, or generate a commit. Hostmark's source
CI demonstrates the base-SHA selection policy, but each private inventory repository deliberately owns its exact workflow.
