<p align="center">
  <img src="docs/assets/banner.svg" alt="Loft — document-work kernel for Claude Code" width="100%">
</p>

<p align="center">
  <img src="https://img.shields.io/badge/version-1.2.0-d89a4a?style=flat-square" alt="version 1.2.0">
  <img src="https://img.shields.io/badge/license-Apache--2.0-blue?style=flat-square" alt="Apache-2.0">
  <img src="https://img.shields.io/badge/kernel-220%20KB%20%C2%B7%2029%20files-success?style=flat-square" alt="220 KB, 29 files">
  <img src="https://img.shields.io/badge/skills-14-success?style=flat-square" alt="14 skills">
  <img src="https://img.shields.io/badge/runtime%20services-0-success?style=flat-square" alt="zero runtime services">
  <img src="https://img.shields.io/badge/contract-81%20lines-success?style=flat-square" alt="81-line contract">
</p>

<p align="center">
  <b>English</b> · <a href="README.ru.md">Русский</a>
</p>

---

Loft is a small kernel for document work in
[Claude Code](https://claude.com/claude-code). It sets the agent up as a
working systems/business analyst: writing specs, maintaining a wiki mirrored
from Confluence, auditing a documentation corpus. Everything beyond that is
deliberately left out.

The name follows [Keel](https://github.com/bogdanov-igor/keel), my kernel
for product development. The two share the layout, the installer approach
and most of the plumbing; this one is for document work.

Loft replaced specos, a setup I retired in June 2026 after finally working out
why it kept "getting dumber" on ordinary markdown work. The overhead was
eating the context. Two MCP servers that markdown work never used cost some
20–30k tokens of tool schemas in every session and in every subagent, and
per-task ceremony filled the dialog with tool output until early auto-compact
threw away what the session knew. From the chair, that looks exactly like
amnesia. Loft's always-on footprint is a single contract of about 3k tokens,
and it runs no MCP servers, vector indexes or daemons of its own. The full
post-mortem, including what was and wasn't measured, is in
[why-loft](docs/en/why-loft.md).

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
moves the predecessor's machinery into quarantine without deleting anything —
see the [migration guide](docs/en/migration.md).

### Or do it yourself

```sh
cd /path/to/project                    # tgz + .sha256 copied here
shasum -c loft_1.2.0.tgz.sha256        # integrity first: expect "OK"
tar -xzf loft_1.2.0.tgz
bash loft/install.sh                   # no argument = install right here
```

From the source repo instead: `bash install.sh /path/to/project`.

Updating is the same command: get the newer loft, re-run `install.sh`. Kernel
files are replaced, project state is never touched, and skills or agents you
added yourself are carried over. A `SessionStart` hook prints one line when a
newer loft exists — next to the project (a `loft/` folder or `$LOFT_HOME`) or
in [Releases](https://github.com/bogdanov-igor/loft/releases) (cached for 24h,
3s ceiling). When you're current it prints nothing, and any failure exits
quietly.

Dependencies: `python3` (all kernel scripts are stdlib); `pandoc` + `lxml`
only if you use the `ingest-*` skills.

## What's inside

- The contract, [`.claude/CLAUDE.md`](bundle/.claude/CLAUDE.md): 81 lines,
  ~3k tokens, the only thing that is always in context. It states the
  profession and points to the rest; procedures live in skills and load when
  used. The core working rule is written into it verbatim: no invented facts.
  Every claim either comes from a source or is explicitly marked as an
  assumption or an open question.
- 14 lazily loaded skills. Spec work: `tz-write`, `tz-adapt`, `tz-audit`,
  `tz-elicit` (question banks for 6 task types). Corpus work:
  `ingest-confluence`, `ingest-docs`, `review-intake`, `link-check`,
  `knowledge-map`. Process: `spec-bootstrap`, `deliver-pdf`, `remember`,
  `stage`, `migrate-specos`.
- Two subagents. `scout` reads big page batches so the main window stays
  clean; `verifier` accepts finished documents in a fresh context. The split
  is about context isolation, nothing else.
- Two hooks: `leak-guard` keeps secrets and internal addresses out of docs,
  and there is a silent update check.
- File memory: notes under `memory/` with a one-line-per-note index,
  `BACKLOG.md` as the single work queue, and `QUESTIONS.md` for open
  stakeholder questions, each with a note on how work resumes once answered.

A document counts as done when the `verifier` agent confirms it in a fresh
context. It checks five things: fidelity to the request, whether claims are
backed, link integrity, structural completeness, internal consistency.

## What it leaves out

- No MCP servers by default, no vectors, no embeddings, no Ollama. A corpus of
  a few hundred markdown pages is searched by reading an index and grepping.
  specos seeded serena and playwright into every project unconditionally;
  their schemas cost ~20–30k tokens per session and per subagent, and when the
  local embedding daemon was down, degraded search looked like memory loss.
- No per-task ceremony: no runs log, no schema validation, no multi-gate
  verify on every touch. Small work (one page, low risk) leaves no process
  files behind. Big work (a full spec, a corpus audit, a restructuring)
  leaves exactly two: `stages/NNN-slug/brief.md` before and a verified
  `report.md` after.
- No patching of other people's extensions. Diagrams are stored as `mermaid`
  fences and render wherever the corpus is read.

The boundary rule, from the roadmap: a script in the kernel can only be a
deterministic data converter (input in, output out). Checks of meaning are
written as instructions to agents in skills. Anything with state, history or
a UI belongs outside the kernel.

## The Confluence converter

The skill `ingest-confluence` turns a Confluence HTML space export into a
markdown wiki with `[[wikilinks]]`. The conversion is deterministic (pandoc +
lxml); no LLM touches the content on the way through.

- Tables are converted HTML→GFM by the converter's own writer. A table that
  can't be represented in GFM stays as HTML and is logged with the reason,
  never silently mangled.
- Attachment links get their names back from the export's
  `data-linked-resource-default-alias` attribute, instead of showing
  `download.xhtml?...`.
- Re-running the ingest updates the snapshot: stale pages are removed (files
  without a `confluence_id` are never touched) and you get a change report —
  `wiki/_CHANGES-<date>.md` for people, `wiki/.ingest.json` for scripts.
- `--space` and `--base-url` make it work for any space; the snapshot date is
  read from the export itself. `fix_tables.py` upgrades wikis converted by v1
  in place, idempotently.
- With `--unroll-pre`, tables holding multi-line JSON/XML examples become
  plain GFM and the code moves below the table as fenced blocks, byte for
  byte. With `--expand-spans`, tables with merged cells (colspan/rowspan)
  become plain GFM too: rowspan repeats the value, colspan pads with empty
  cells — layout loss, never data loss.
- Confluence attribute noise (`class`/`style`/`rel`/`data-*`) is scrubbed
  before pandoc, so links come out as `[text](url)` → `[[wikilinks]]`
  instead of raw `<a class=...>` HTML; Jira avatars and emoticons are
  dropped. `fix_tables.py` applies the same cleanup to already-converted
  wikis.

Numbers from the corpus it was built against, a banking wiki of 446 pages:
468 of 609 raw HTML tables came out as clean GFM (the rest are logged
fallbacks, nearly all multi-line JSON examples), 0 empty links, a 336-page
tree byte-identical to the reference conversion, and 0 broken links out of
3,645 after `link-check`.

## The corpus is a graph

The corpus speaks the Foam/Obsidian dialect on purpose: `[[wikilinks]]`
resolved by basename, `![[embeds]]`, `\|`-escaped aliases in tables. Open the
project folder in [Obsidian](https://obsidian.md), or install
[Foam](https://foambubble.github.io/foam/) in VS Code (the installer seeds the
extension recommendation), and the graph view, backlinks and link navigation
just work. `link-check` resolves links the same way those tools do (basename,
case-insensitive, NFC), so if it comes back green, the graph has no holes.

## Tests

`test/run.sh` runs 77 self-tests over the kernel's scripts: `link_check`, the
table writer, `fix_tables` idempotence, the migration sweep, the update check
and installer scenarios — all offline, against throwaway fixtures.
`build-archive.sh` runs the suite as a release gate and then does a real
install from the freshly built archive into a temp directory as a final
check. The 0.1.0 release also went through an independent review: 20 findings,
all closed, the 3 critical ones in code inherited from the v1 converter.

## Layout in a deployed project

```text
.claude/      kernel (kernel-owned: reinstalling overwrites it)
wiki/         Confluence mirror — generated, never edited by hand
spec/         authored specs and decisions + _STRUCTURE.md (structure profile)
inbox/        incoming files before conversion; originals are kept
memory/       project memory: MEMORY.md index + lessons/antipatterns/patterns/structures
stages/       big-work artifacts: NNN-slug/brief.md + report.md
BACKLOG.md    the one canonical work queue
QUESTIONS.md  open stakeholder questions, each with a resume plan
```

## Coming from specos?

Install loft, then run the `migrate-specos` skill. It moves the predecessor's
machinery — bundles, distributions, engine state — into a timestamped
`.loft-migration/` folder with a restore manifest. Nothing is deleted, and
project state (wiki, specs, memory, backlog) is never touched. The installer
also refuses to carry the MCP tax over: a specos-era `.mcp.json` goes to
backup, not into your next session.

Details in the [migration guide](docs/en/migration.md).

## Documentation

| | English | Русский |
|---|---|---|
| Install & update | [install](docs/en/install.md) | [установка](docs/ru/install.md) |
| Architecture | [architecture](docs/en/architecture.md) | [архитектура](docs/ru/architecture.md) |
| Migrating from specos | [migration](docs/en/migration.md) | [миграция](docs/ru/migration.md) |
| What changed, measured | [why-loft](docs/en/why-loft.md) | [почему loft](docs/ru/why-loft.md) |

## Licence

[Apache-2.0](LICENSE) © 2026 **Igor Bogdanov** · <bogdanov.ig.alex@gmail.com>

Free to use, fork and build on, commercially included. Keep the attribution
and note what you changed.
