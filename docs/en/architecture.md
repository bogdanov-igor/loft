# Architecture

Loft has one idea: **files are the only shared truth, and the agent is a
co-author analyst.** Everything below follows from it.

## The contract

[`.claude/CLAUDE.md`](../../bundle/.claude/CLAUDE.md) — 81 lines, ~3k tokens,
always in context, and the only thing that always is. It states two things:

**The profession.** The agent is the project's systems/business analyst on the
owner's side. It writes specs (whole or in parts), analyzes and audits other
people's documents, bootstraps the structure of new projects. The owner sets
direction and answers questions; wording, completeness, coherence and
substantiation belong to the agent. The core rule: **not a single invented
fact** — every claim is either derivable from a source or explicitly marked
as an assumption or a question.

**Ten working rules.** Two tiers of work; memory before non-trivial work and
`remember` after a non-obvious lesson; spec writing routed through `tz-write`
/ `tz-adapt` / `spec-bootstrap`, incomplete requests through `tz-elicit`; done
means a `verifier` verdict, not a self-report; audits file findings into
`BACKLOG.md`; facts are cited by `[[wikilink]]`, not retold; incoming files
only through `inbox/`; secrets never in docs; subagents for context isolation,
not roles; sessions start from `QUESTIONS.md` and the top of `BACKLOG.md`.

The rest of the kernel is pointers. Procedures live in skills and enter
context only when used.

## The files

```text
wiki/         generated Confluence mirror — never edited by hand;
              meaning changes go to Confluence or to spec/
spec/         authored documents: specs, decisions, glossary,
              _STRUCTURE.md (the project's spec-structure profile)
inbox/        incoming docx/pdf/images/html before conversion; originals kept
memory/       lessons · antipatterns · patterns · structure profiles,
              indexed by MEMORY.md (strict one-liners)
stages/       NNN-slug/brief.md + report.md — big work only
BACKLOG.md    the one canonical work queue: tasks and audit findings
QUESTIONS.md  open questions to owner and stakeholders,
              each with a plan for how work resumes after the answer
```

A conclusion worth surviving the session gets written the moment it exists.
Unwritten insight dies with the context window.

**Memory** is markdown notes plus a strict one-line index. Retrieval is
reading the index and grepping. No embedding model, no vector store, no
daemon — see [why-loft](why-loft.md) for what happened when there was one.

**`QUESTIONS.md`** is the analyst's counterpart to a parking lot: a critical
question without an answer blocks a spec, so it is filed with a continuation
plan instead of stalling silently. At session start, answered questions return
their work to `BACKLOG.md`.

## Two tiers of work

| | Small | Big |
|---|---|---|
| **What** | One page, low risk | Full spec, corpus audit, restructuring, multi-session work |
| **Protocol** | Do it, check it, move on | Skill `stage` |
| **Artifacts** | None | `stages/NNN-slug/brief.md` before, verified `report.md` after |

That is the whole ceremony budget. The predecessor ran the same run-log →
schema-validation → multi-gate pipeline for a one-line fix as for a full spec;
ceremony on small work is pure tax, paid in context.

## Skills

14 markdown procedures under `.claude/skills/`, lazy-loaded — a skill costs
nothing until it is used.

**Spec work:**

- **`tz-write`** — write a spec or a section in the project's structure; every
  claim carries a source link or an explicit assumption marker; acceptance is
  the `verifier`'s verdict.
- **`tz-adapt`** — learn a foreign spec structure from samples, fix the
  profile in `memory/structures/`, then write in it via `tz-write`. For
  customer documents and other people's projects.
- **`tz-audit`** — audit a document or corpus along six axes: completeness
  against the structure profile, contradictions (including name synonyms for
  one system, checked against the glossary), link integrity via `link-check`,
  substantiation, staleness, hygiene. Traffic-light report; findings go to
  `BACKLOG.md`. A corpus audit is a stage.
- **`tz-elicit`** — interrogate an incomplete request into a working brief:
  `banks.md` carries question banks for six task types (integration,
  migration, UI/UX, functionality, bug, general). Questions go in one batch;
  critical ones left unanswered go to `QUESTIONS.md`, the rest become marked
  assumptions.

**Corpus work:**

- **`ingest-confluence`** — the deterministic Confluence converter (below).
- **`ingest-docs`** — incoming docx/pdf/images/html → markdown through
  `inbox/`. The original is kept and linked from the conversion; docx converts
  deterministically via pandoc; pdf and images become a synopsis with a
  mandatory marker and a link to the original.
- **`link-check`** — `link_check.py` (stdlib, deterministic): broken
  `[[wikilinks]]`, `![[embeds]]`, relative markdown links and images, orphan
  pages. Resolution is Foam/Obsidian-style by basename, NFC-normalized and
  case-folded; lines inside code fences are skipped. Exit code 1 on breakage —
  pipeline-ready.

**Process:**

- **`spec-bootstrap`** — stand up a new project's documentation: corpus
  layout, spec-structure profile, glossary, decision register. The structure
  is agreed with the owner *before* mass writing.
- **`remember`** — write a lesson, antipattern, pattern or structure profile
  to project memory with a strict one-line index entry.
- **`stage`** — the big-work protocol: brief before, verified report after.
- **`migrate-specos`** — quarantine the predecessor's machinery with a
  rollback manifest; see [migration](migration.md).

Skills you write yourself live alongside them and **survive kernel
reinstalls** automatically.

## The Confluence converter

The flagship, and the reason the boundary rule exists. `ingest-confluence`
turns a Confluence HTML space export into a markdown wiki with `[[wikilinks]]`
— **deterministically**, with pandoc + lxml. No LLM rewrites a fact in
transit, which is what makes the output verifiable at all.

- **Own HTML→GFM table writer.** A table that cannot survive the trip stays
  as HTML and is logged with a reason — never silently mangled.
- **Attachment link names** are restored from the export's
  `data-linked-resource-default-alias` attribute, so links read as file names,
  not `download.xhtml?...`.
- **Re-ingest updates the snapshot.** Stale pages are removed on
  re-conversion; files without a `confluence_id` in front-matter are
  untouchable, so hand-written pages inside `wiki/` are safe. Since 1.0.0 a
  re-ingest also produces a change report: `wiki/_CHANGES-<date>.md` for
  people, `wiki/.ingest.json` for machines.
- **Generalized:** `--space` sets the space key, `--base-url` the Confluence
  address for source links; the snapshot date is read from the export itself.
- **`fix_tables.py`** — an idempotent postprocessor that upgrades wikis
  converted by v1 (HTML tables → GFM, attachment link names) in place.

Proven on a real banking corpus of **446 pages**: 468 of 609 raw HTML tables
converted to clean GFM (the remainder are logged fallbacks, almost all
multi-line JSON examples), 0 empty links, a 336-page tree byte-identical to
the reference conversion, 0 broken links out of 3,645.

## The boundary rule

What keeps the kernel from growing back into its predecessor:

- **A script in the kernel may only be a deterministic data converter**
  (input → output): `convert.py`, `fix_tables.py`, `link_check.py`. That is
  the complete list.
- **Checks of meaning** — terminology, completeness, sanitation, tracing —
  are *instructions to agents* in skills: the agent reads the skill and does
  the check itself, with eyes and grep.
- **Features with state, history or UI** — git/diff/versioning, a graph
  screen, a kanban — live outside the kernel. No embeddings, vectors, own
  MCP, daemons or schedules — ever.

## Subagents

Two, decomposed by **context isolation** — never by job title:

- **`scout`** — reads the corpus and external sources so the main window does
  not. Big page batches are read by parallel scouts, not the main thread.
- **`verifier`** — independent acceptance of documents with a fresh context,
  along five axes: fidelity to the request, substantiation, link integrity,
  structure, consistency. A self-report is a claim, not a verdict.

## Hooks

Two:

- **`leak-guard.sh`** — secrets and internal addresses (IPs, hosts, accounts,
  tokens) never land in docs. Values go to `.secrets.env`; documents carry
  `{{secret:KEY}}` or a `{SYSTEM_NAME}` placeholder. The hook blocks the
  violating write.
- **`update-check.sh`** (`SessionStart`) — one line when a newer loft sits
  next to the project (a `loft/` folder or `$LOFT_HOME`); silence is the
  default path. No network calls; any failure exits quietly and never blocks
  a session.

## Testing the kernel

The kernel is scripts, and a script that is never exercised rots like any
other code. `test/run.sh` drives the shipped scripts against throwaway
fixtures in a temp directory, offline: 29+ assertions over `link_check`, the
table writer, `fix_tables` idempotence, the migration `sweep.sh`,
`update-check.sh` and installer scenarios. Each case is either a real bug
caught by hand — including during the independent verification — or a property
the documentation promises.

It is a release gate, not a suggestion: `build-archive.sh` runs the suite
first and refuses to build if anything fails, then unpacks the archive it just
built into a temp directory and performs a real install to verify it. The
installer itself ends with a self-check (contract present, hooks executable,
skill count, `link_check` runs) and fails loudly rather than hand over a
broken kernel.

## What is kernel-owned vs project-owned

```text
.claude/     kernel-owned — reinstalling overwrites it. Never edit in place.
everything   project-owned — the installer seeds it once where absent and
else         never touches it again.
```

Kernel changes happen in the loft repo and reach projects by reinstall.
Editing `.claude/` inside a deployed project means your change dies at the
next update.
