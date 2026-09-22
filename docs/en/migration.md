# Migrating from specos

A project that ran specos carries two different things: the machinery — the
bundle, the distributions, the engine state — and the state: the wiki, the
specs, the memory, the backlog. Migration sweeps the first, preserves the
second, and is careful never to confuse them.

## The rules

1. Nothing is deleted. Residue is moved to `.loft-migration/<timestamp>/`
   with a manifest that lists every path and how to restore it.
2. Project state is never touched: `wiki/`, `spec/`, `docs/`, `inbox/`,
   `memory/`, `BACKLOG.md`, `QUESTIONS.md` stay exactly as they were.
3. Ambiguity is flagged, not guessed. A script doesn't get to decide what is
   yours; it reports and leaves the path alone.

## Steps

**1. Install loft** over the project as usual:

```sh
cd /path/to/project
shasum -c loft_1.3.1.tgz.sha256 && tar -xzf loft_1.3.1.tgz
bash loft/install.sh
```

The old `.claude` moves to `.claude.bak.<timestamp>`. Skills and agents
belonging to specos itself the installer recognizes by the wire lists in
`.data/.specos-wire-*.list` and leaves in the backup; yours it carries over.
With no wire lists left there is nothing to tell them apart by, so everything
stays in the backup — the installer says so on a line of its own.
Permissions (`settings.local.json`), commands, rules and output styles move
either way.

The specos `.mcp.json` — the ~20–30k-token schema tax — goes to backup too.
After `.mcp.json` changes, restart the Claude Code session: MCP servers are
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

The sweep does not touch `.mcp.json` — neither in preview nor with `--apply`.
The MCP tax comes off once, at install time; if the config is still there,
the installer judged it yours, and what to do about it is your call.

## What moves, what stays

| Swept to quarantine | Never touched |
|---|---|
| `specos/`, `skillforge/` bundles and their archives | `wiki/`, `spec/`, `docs/`, `inbox/` |
| `.data/` engine state: `.specos-*`, `runs.jsonl`, `memory-index.json`, `bin/`, `backup/` | `memory/`, `BACKLOG.md`, `QUESTIONS.md` |
| | `.secrets.env`, `.mcp.json` |

Anything ambiguous is reported for you to decide and never moved. Restoring
is one `mv`, spelled out in the manifest:

```sh
mv .loft-migration/<ts>/<path> <path>
```

## Rescuing the memory

specos kept its knowledge notes inside `.claude`, so they are now in the
backup: `.claude.bak.<timestamp>/memory/knowledge`. The machinery is dead,
but some of the lessons in there may still be alive. Read through and carry
the ones that hold up into `memory/` via the `remember` skill: each gets a
one-line entry in `memory/MEMORY.md`, instead of a bulk copy nobody indexes.
Notes about specos' own machinery you can leave behind.

## Then re-audit

This is what the migration is for. The kernel changed underneath the corpus,
and specos-era verdicts don't carry over: what marked them verified were
gates and memory the diagnosis found unreliable. Earning them again means
running `tz-audit` on the corpus. An audit at that scale is a `stage` — brief
before, verified report after; findings go to `BACKLOG.md`, and at 20+ open
ones you burn down before auditing further. The `--apply` sweep has already
filed the re-audit line into `BACKLOG.md`, so the step is waiting at the top
of the queue.

## Cleaning up

Once the project has run clean for a while, delete the quarantine and the old
kernel backups:

```sh
rm -rf .loft-migration/ .claude.bak.*
```

Nothing in loft depends on them.
