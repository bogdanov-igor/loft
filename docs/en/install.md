# Install & update

## Requirements

- [Claude Code](https://claude.com/claude-code)
- `bash`, `tar` — present on macOS and Linux out of the box
- `python3` — all kernel scripts are stdlib-only
- Optional `pandoc` — for the `ingest-confluence`, `ingest-docs`,
  `review-intake` and `deliver-pdf` skills; `lxml` — for `ingest-confluence`
  alone

Nothing else: no MCP server, no daemon, no index to build.

## Quickstart

**1.** Download `loft_1.3.0.tgz` and `loft_1.3.0.tgz.sha256` from
[Releases](https://github.com/bogdanov-igor/loft/releases/latest) into your
project folder.

**2.** Open the project in Claude Code and say:

> Install loft from the archive in this folder: verify the sha256, unpack it,
> run `loft/install.sh`, then tell me what it set up.

**3.** Ran specos before — add "clean up the specos leftovers and propose
the re-audit": the machinery goes to quarantine, nothing is deleted, see
[migration](migration.md).

## By hand

Both paths run the same installer.

### From the archive

```sh
cd /path/to/project                 # copy both files here
shasum -c loft_1.3.0.tgz.sha256     # verify integrity first: expect "OK"
tar -xzf loft_1.3.0.tgz
bash loft/install.sh                # no argument = install into this directory
```

The `loft/` folder can stay in the project (the update check will use it, and
re-running `install.sh` updates the kernel) or be deleted. If it stays, add
`loft/` and the `.tgz` to `.gitignore`.

### From the source repo

```sh
git clone https://github.com/bogdanov-igor/loft.git
bash loft/install.sh /path/to/project
```

## What the installer does

| Action | Detail |
|---|---|
| Installs the kernel | Copies `bundle/.claude` in as a real directory, never a symlink — symlinks break hook path resolution and per-project isolation. An existing `.claude` is moved to `.claude.bak.<timestamp>` first; two runs within the same second get different backup names, so the new one cannot land inside the old. Every `*.sh` inside the new `.claude` gets the execute bit back: unpacking and copying drop it, and the hooks and `sweep.sh` need it straight away. |
| Stamps the version | Writes `.claude/VERSION`, which the update check reads. |
| Preserves your skills and agents | Skill directories and agent files the kernel does not ship are carried over from the previous `.claude`. Exception: in a specos-managed `.claude`, specos' own skills and agents are recognized by its wire lists and stay in the backup, so the predecessor's machinery does not ride back in. |
| Preserves your Claude Code setup | Restores `settings.local.json` (permissions), `commands/`, `rules/` and your own output styles from the backup — file by file, because `output-styles/analyst.md` is shipped by the kernel. specos' `commands/` and `rules/` do not count as yours and stay in the backup. |
| Seeds project state | Creates `memory/` (with `lessons/antipatterns/patterns/structures`), `stages/`, `spec/`, `spec/_reference/`, `spec/_reviews/`, `inbox/`, `inbox/done/`, `BACKLOG.md`, `QUESTIONS.md`, `memory/MEMORY.md` — only where absent. Existing state is never overwritten. |
| Protects secrets | Adds `.secrets.env` to `.gitignore`. A file with no trailing newline gets one first, or the last pattern would run into the new one. |
| Seeds the corpus graph | Creates `.vscode/extensions.json` recommending Foam and a mermaid preview — the graph and backlinks in VS Code in one click. Only when no recommendations file exists yet. |
| Drops the MCP tax | A specos-era `.mcp.json` (serena + playwright + memory ≈ 20–30k tokens of schemas per session) is moved to backup; your own servers, if any, you restore by hand. A config counts as specos' when a server itself is specos' — by name or by launch path, not by any mention of the word in a comment. Any other `.mcp.json` is left as is, with a reminder that every server costs schema tokens in every session. |
| Detects residue | Runs the migration sweep in preview mode and reports specos/skillforge machinery, pointing at the `migrate-specos` skill. It moves nothing itself. |
| Self-checks | Verifies the contract is present, hooks are executable, the skill count is right, and `link_check` actually runs. On failure it rolls the install back: the failed kernel is removed and the previous `.claude` returns from backup — a half-installed kernel where a working one used to be is worse than an update that never happened. |

### Output style

The kernel drops `.claude/output-styles/analyst.md` in place but does not
turn it on. The style lifts Claude Code's instructions about writing code:
kernel tools get run as they are, scripts are not improved on the fly, and a
broken tool is a finding for the owner rather than a task to go fix. Turn it
on with `/config` → Output style → `analyst`.

## Updating

The simplest path: download the new archive into the project folder and say:

> Update loft from the archive in this folder.

By hand it is the same command as the install, from a newer loft folder (a
fresh release, or `git pull`):

```sh
cd /path/to/project
bash loft/install.sh
```

Kernel files are replaced. Project state — wiki, specs, memory, stages,
backlog, questions, your own skills, agents and Claude Code settings — is not
touched. Old `.claude.bak.*` backups can be pruned freely.

### How you learn an update exists

A `SessionStart` hook compares `.claude/VERSION` against a distribution lying
nearby (the `loft/` folder in the project, or `$LOFT_HOME`) and against the
latest [GitHub release](https://github.com/bogdanov-igor/loft/releases).
Something strictly newer — one line; you are current — no line at all, so the
normal case costs zero tokens.

The GitHub lookup is cached for 24 hours on a good answer and an hour on a
bad one — starting a session on a train or behind a firewall shouldn't cost
three seconds every time — and it hits a hard 3-second ceiling. With neither
`XDG_CACHE_HOME` nor `HOME` set there is nowhere for the cache to live: the
release check is skipped, the local sources keep working. Every failure path
exits silently, and the check cannot block a session. Opt out entirely with
`LOFT_NO_UPDATE_CHECK=1`.

## Building the archive (maintainers)

```sh
bash build-archive.sh    # → dist/loft_<version>.tgz + .sha256
```

`build-archive.sh` itself is not shipped inside the archive. It runs
`test/run.sh` first — over 500 self-tests over the kernel's scripts, offline,
on throwaway fixtures — and refuses to build if anything fails. It then
unpacks the archive into a temp directory and performs a real install,
verifying the result end to end. The build is hermetic: its own cache instead
of the real `~/.cache`, no network.

The archive is packed by `python3` (`tarfile` + `gzip`) rather than the
system `tar`: ustar format, entries ordered by the bytes of their path,
uid/gid 0 with empty owner names, 0755 on directories and executables and
0644 on everything else, mtime 2020-01-01 UTC, gzip with no file name or
timestamp in the stream. So the sha256 comes out the same on any OS and does
not depend on who built it — bsdtar and GNU tar pack the header fields
differently. Unpacking is a plain `tar -xzf`.
