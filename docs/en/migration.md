# Migrating from specos

A project that ran specos carries two different things: the machinery (the
bundle, the distributions, the engine state — dead weight once the system is
gone) and the state (the wiki, the specs, the memory, the backlog — the part
worth keeping). Migration sweeps the first, preserves the second, and is
careful never to confuse them.

## The rules

1. Nothing is deleted. Residue is moved to `.loft-migration/<timestamp>/`
   with a `MANIFEST` that lists every path and how to restore it.
2. Project state is never touched: `wiki/`, `spec/`, `docs/`, `inbox/`,
   `memory/`, `BACKLOG.md`, `QUESTIONS.md` stay exactly as they were.
3. Ambiguity is flagged, not guessed. A script doesn't get to decide what is
   yours; it reports and leaves the path alone.

## Steps

**1. Install loft** over the project as usual:

```sh
cd /path/to/project
shasum -c loft_1.2.0.tgz.sha256 && tar -xzf loft_1.2.0.tgz
bash loft/install.sh
```

The installer moves the old `.claude` to `.claude.bak.<timestamp>` and
recognizes a specos-managed one: specos' own skills and agents (identified by
its wire lists) stay in the backup, while skills and agents you wrote
yourself are carried over. The specos `.mcp.json` — the ~20–30k-token schema
tax — goes to backup too; your own servers, if you had any, you restore by
hand. Finally, the installer runs the sweep in preview mode and reports what
it found, without moving anything.

If `.mcp.json` changed, restart the Claude Code session: MCP servers are
loaded at startup, so a stale server stays connected until you do.

**2. Preview the sweep.** Read-only, changes nothing:

```sh
bash .claude/skills/migrate-specos/sweep.sh
```

**3. Sweep.** In Claude Code, invoke the `migrate-specos` skill, or run it
directly:

```sh
bash .claude/skills/migrate-specos/sweep.sh --apply
```

`--apply` quarantines the machinery and also files the re-audit line into
`BACKLOG.md`, so the follow-up survives the session.

## What moves, what stays

| Swept to quarantine | Never touched |
|---|---|
| `specos/`, `skillforge/` bundles and their archives | `wiki/`, `spec/`, `docs/`, `inbox/` |
| `.data/` engine state: `.specos-*`, `runs.jsonl`, `memory-index.json`, `bin/`, `backup/` | `memory/`, `BACKLOG.md`, `QUESTIONS.md` |
| | `.secrets.env` |

Ambiguous paths are reported for you to decide and never moved. Restoring
anything is one `mv`, spelled out in the manifest:

```sh
mv .loft-migration/<ts>/<path> <path>
```

## Rescuing the memory

specos kept its knowledge notes inside `.claude`, so they are now in the
backup: `.claude.bak.<timestamp>/memory/knowledge`. The machinery is dead,
but some of the lessons in there may still be good. Read through them and
carry the ones that hold up into `memory/` via the `remember` skill — each
gets a proper one-line entry in `memory/MEMORY.md`, instead of a bulk copy
nobody indexes. Notes that only described specos' own machinery can be left
behind.

## Then re-audit

This is what the migration is for. The kernel changed underneath the corpus,
and specos-era verdicts don't carry over: whatever its pipeline marked as
verified was marked under gates and memory that the diagnosis found
unreliable. Those verdicts have to be earned again:

- Run `tz-audit` on the corpus. An audit at corpus scale is a `stage` — brief
  before, verified report after. Findings go to `BACKLOG.md`; at 20+ open
  findings, burn down before auditing more.
- The `--apply` sweep has already filed the re-audit line into `BACKLOG.md`,
  so this step will be waiting at the top of the queue.

## Cleaning up

Once the project has run clean for a while, delete the quarantine and the old
kernel backups:

```sh
rm -rf .loft-migration/ .claude.bak.*
```

Nothing in loft depends on them.
