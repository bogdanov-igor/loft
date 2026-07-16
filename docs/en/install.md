# Install & update

## Requirements

- [Claude Code](https://claude.com/claude-code)
- `bash`, `tar` — present on macOS and Linux out of the box
- `python3` — all kernel scripts are stdlib-only
- Optional: `pandoc` + `lxml`, needed only by the `ingest-confluence` and
  `ingest-docs` skills

Loft needs no runtime services: no MCP server, no daemon, no index to build.
The kernel is markdown plus a few deterministic scripts.

## Quickstart

**1.** Download `loft_1.2.0.tgz` and `loft_1.2.0.tgz.sha256` from
[Releases](https://github.com/bogdanov-igor/loft/releases/latest) into your
project folder.

**2.** Open the project in Claude Code and say:

> Install loft from the archive in this folder: verify the sha256, unpack it,
> run `loft/install.sh`, then tell me what it set up.

**3.** If the project ran specos before, add:

> Clean up the specos leftovers and propose the re-audit.

Claude verifies the checksum, unpacks, installs and reports. The cleanup step
quarantines the predecessor's machinery without deleting anything — see
[migration](migration.md).

## By hand

Two paths, both running the same installer.

### From the archive

You have two files side by side: `loft_1.2.0.tgz` and its `.sha256` sidecar.

```sh
cd /path/to/project                 # copy both files here
shasum -c loft_1.2.0.tgz.sha256     # verify integrity first: expect "OK"
tar -xzf loft_1.2.0.tgz
bash loft/install.sh                # no argument = install into this directory
```

The unpacked `loft/` folder can stay in the project (the update check will
use it, and re-running `install.sh` updates the kernel) or be deleted. If it
stays, add `loft/` and the `.tgz` to `.gitignore`.

### From the source repo

```sh
git clone https://github.com/bogdanov-igor/loft.git
bash loft/install.sh /path/to/project
```

## What the installer does

| Action | Detail |
|---|---|
| Installs the kernel | Copies `bundle/.claude` in as a real directory, never a symlink — symlinks break hook path resolution and per-project isolation. An existing `.claude` is moved to `.claude.bak.<timestamp>` first. |
| Stamps the version | Writes `.claude/VERSION`, which the update check reads. |
| Preserves your skills and agents | Skill directories and agent files the kernel does not ship are carried over from the previous `.claude`. Exception: in a specos-managed `.claude`, specos' own skills and agents are recognized by its wire lists and stay in the backup, so the predecessor's machinery does not ride back in. |
| Seeds project state | Creates `memory/` (with `lessons/antipatterns/patterns/structures`), `stages/`, `spec/`, `inbox/`, `BACKLOG.md`, `QUESTIONS.md`, `memory/MEMORY.md` — only where absent. Existing project state is never overwritten. |
| Protects secrets | Adds `.secrets.env` to `.gitignore`. |
| Drops the MCP tax | A specos-era `.mcp.json` (serena + playwright + memory ≈ 20–30k tokens of schemas per session) is moved to backup; your own servers, if any, you restore by hand. Any other `.mcp.json` is left as is, with a reminder that every server costs schema tokens in every session. |
| Detects residue | Runs the migration sweep in preview mode and reports specos/skillforge machinery, pointing at the `migrate-specos` skill. It moves nothing itself. |
| Self-checks | Verifies the contract is present, hooks are executable, the skill count is right, and `link_check` actually runs. On failure it says so loudly instead of handing over a broken kernel. |

## Updating

The simplest path: download the new archive into the project folder and say:

> Update loft from the archive in this folder.

By hand it is the same command as the install. Get the newer loft folder
(download the release, or `git pull`) and run:

```sh
cd /path/to/project
bash loft/install.sh
```

Kernel files are replaced. Project state — wiki, specs, memory, stages,
backlog, questions, your own skills and agents — is not touched. Old
`.claude.bak.*` backups can be pruned freely.

### How you learn an update exists

A `SessionStart` hook compares `.claude/VERSION` against every source it can
see — a loft distribution lying nearby (the `loft/` folder in the project, or
`$LOFT_HOME`) and the latest [GitHub release](https://github.com/bogdanov-igor/loft/releases)
— and prints one line when something is strictly newer. When you are current
it prints nothing, so the normal case costs zero tokens.

The GitHub lookup is cached for 24 hours and has a hard 3-second ceiling, so
a slow network never delays a session; every failure path exits silently. Opt
out entirely with `LOFT_NO_UPDATE_CHECK=1`. The check cannot block a session.

## Building the archive (maintainers)

```sh
bash build-archive.sh    # → dist/loft_<version>.tgz + .sha256
```

`build-archive.sh` is not shipped inside the archive. It runs `test/run.sh`
first — 103 self-tests over the kernel's scripts, offline, on throwaway
fixtures — and refuses to build if anything fails. It then unpacks the archive
it just built into a temp directory and performs a real install to verify the
result end to end.
