# Migrating from specos

A project that ran specos carries two very different things: its **machinery**
(the bundle, the distributions, the engine state — dead weight once the system
is gone) and its **state** (the wiki, the specs, the memory, the backlog — the
valuable part). Migration sweeps the first and preserves the second, and never
confuses them.

## The rules

1. **Nothing is deleted.** Residue is *moved* to `.loft-migration/<timestamp>/`
   with a `MANIFEST` that lists every path and how to restore it.
2. **Project state is never touched.** `wiki/`, `spec/`, `docs/`, `inbox/`,
   `memory/`, `BACKLOG.md`, `QUESTIONS.md` — all yours, all untouched, to the
   byte.
3. **Ambiguity is flagged, not guessed.** A script does not get to decide what
   is yours. It reports and leaves it alone.

## Steps

**1. Install loft** over the project as usual:

```sh
cd /path/to/project
shasum -c loft_1.1.0.tgz.sha256 && tar -xzf loft_1.1.0.tgz
bash loft/install.sh
```

The installer moves the old `.claude` to `.claude.bak.<timestamp>` and
recognizes a specos-managed one: specos' own skills and agents (identified by
its wire lists) stay in the backup instead of riding back in, while skills and
agents you wrote yourself are carried over. The specos `.mcp.json` — the
~20–30k-token schema tax — goes to backup too; your own servers, if you had
any, you restore by hand. Finally, the installer runs the sweep in preview
mode and reports what it found — **without moving anything**.

If `.mcp.json` changed, restart the Claude Code session: MCP servers are
loaded at startup, so a stale server stays connected until you do.

**2. Preview the sweep** — read-only, changes nothing:

```sh
bash .claude/skills/migrate-specos/sweep.sh
```

**3. Sweep**, in Claude Code, by invoking the `migrate-specos` skill (or
directly):

```sh
bash .claude/skills/migrate-specos/sweep.sh --apply
```

`--apply` quarantines the machinery and files the re-audit line into
`BACKLOG.md` on its own, so the follow-up survives the session.

## What moves, what stays

| Swept to quarantine | Never touched |
|---|---|
| `specos/`, `skillforge/` bundles and their archives | `wiki/`, `spec/`, `docs/`, `inbox/` |
| `.data/` engine state: `.specos-*`, `runs.jsonl`, `memory-index.json`, `bin/`, `backup/` | `memory/`, `BACKLOG.md`, `QUESTIONS.md` |
| | `.secrets.env` |

Ambiguous paths are reported for you to decide — never moved. Restoring
anything is one `mv`, spelled out in the manifest:

```sh
mv .loft-migration/<ts>/<path> <path>
```

## Rescue the memory

specos kept its knowledge notes inside `.claude`, so they are now in the
backup: `.claude.bak.<timestamp>/memory/knowledge`. The machinery is dead;
the lessons in there may not be. Read through them and carry the ones that
still hold into `memory/` via the **`remember`** skill — each gets a proper
one-line entry in `memory/MEMORY.md`, instead of a bulk copy that nobody
indexes. Notes that only described specos' own machinery are exactly the ones
to leave behind.

## Then re-audit — this is the point of migrating

The kernel changed underneath the corpus, and **specos-era verdicts do not
carry over**: what its pipeline marked as verified was marked under gates and
memory that this diagnosis found unreliable. Do not inherit those verdicts —
re-earn them:

- Run **`tz-audit`** on the corpus (an audit at corpus scale is a `stage`:
  brief before, verified report after). Findings go to `BACKLOG.md`; at 20+
  open findings, burn down before auditing more.
- The `--apply` sweep has already filed the re-audit line into `BACKLOG.md`,
  so this step is waiting for you at the top of the queue.

## Cleaning up

Once the project has run clean for a while, delete the quarantine and the old
kernel backups:

```sh
rm -rf .loft-migration/ .claude.bak.*
```

Nothing in loft depends on them.
