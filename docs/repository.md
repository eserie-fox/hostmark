# Inventory repository

## Canonical layout and marker

A Hostmark inventory repository may have any directory name. Its root is identified only by this layout:

```text
<repository-root>/
├── .git/
├── HOSTMARK_REPOSITORY
└── hosts.json
```

`HOSTMARK_REPOSITORY` is a readable regular file containing exactly zero bytes. It is not configuration and carries no
version. `hosts.json` is the existing schema-version-one canonical registry. The Hostmark source checkout intentionally
has neither root file and is not itself an inventory repository.

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
cd <printed-repository>
git add HOSTMARK_REPOSITORY hosts.json
git commit -m "Initialize hostmark repository"
git remote add origin <remote-url>
git push -u origin main
```

Initialization accepts an absent or empty target, validates inputs first, requires system Git, initializes an unborn
`main` branch, and creates only the marker and canonical empty registry. It never stages, commits, configures identity or
a remote, pushes, creates a host UUID, or registers the machine.

## Clone and synchronize

```bash
hostmark repo sync --remote <remote-url>
hostmark check

# Later:
hostmark repo sync && hostmark check
```

An absent or empty target requires `--remote` and is cloned. An existing repository must have a valid marker, be the Git
worktree root, have an `origin`, be on an attached branch with an upstream, and have no tracked changes. Untracked files
do not block synchronization. A supplied `--remote` must exactly match `origin`; Hostmark never changes the remote.

Synchronization runs `git pull --ff-only`, never stashes, resets, cleans, checks out, rebases, commits, pushes, or repairs
divergence. System Git owns credentials. Hostmark disables terminal credential prompts; SSH remotes use BatchMode and
`StrictHostKeyChecking=accept-new`. After clone or pull, Hostmark strictly validates the zero-byte marker and canonical
registry. If validation fails, the Git result remains visible and Hostmark does not roll back or rewrite it.

No other command synchronizes implicitly. In particular, `hostmark check` is local and deterministic.

## Migrating a v0.1 layout

Marker discovery applies only to the v0.2 root layout. For an earlier repository containing `registry/hosts.json`:

1. Move `registry/hosts.json` to root `hosts.json`.
2. Create an empty root `HOSTMARK_REPOSITORY`.
3. Run `hostmark registry validate --registry hosts.json`.
4. Commit the move and marker manually.

Hostmark never performs this migration automatically. A repository that stays on the old layout remains usable through
`--registry /old/path/registry/hosts.json` or `HOSTMARK_REGISTRY=/old/path/registry/hosts.json`.
