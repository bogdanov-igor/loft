<p align="center">
  <img src="docs/assets/banner.svg?v=1.3" alt="Loft — document-work kernel for Claude Code" width="100%">
</p>

<p align="center">
  <img src="https://img.shields.io/badge/version-1.3.5-d89a4a?style=flat-square" alt="version 1.3.5">
  <img src="https://img.shields.io/badge/license-Apache--2.0-blue?style=flat-square" alt="Apache-2.0">
  <img src="https://img.shields.io/badge/kernel-452%20KB%20%C2%B7%2033%20files-success?style=flat-square" alt="452 KB, 33 files">
  <img src="https://img.shields.io/badge/skills-15-success?style=flat-square" alt="15 skills">
  <img src="https://img.shields.io/badge/runtime%20services-0-success?style=flat-square" alt="zero runtime services">
  <img src="https://img.shields.io/badge/contract-149%20lines-success?style=flat-square" alt="149-line contract">
</p>

<p align="center">
  <b>English</b> · <a href="README.ru.md">Русский</a>
</p>

---

Loft is a small kernel for document work in
[Claude Code](https://claude.com/claude-code). The agent in it is a systems
and business analyst: it writes specs, keeps a wiki mirrored from Confluence,
audits a documentation corpus. Everything beyond that is deliberately left out.

The name follows [Keel](https://github.com/bogdanov-igor/keel), my kernel for
product development: same layout, same installer, most of the same plumbing.
Keel is for code, this one is for documents.

One thing to know before you install: the kernel itself is written in Russian.
The contract, all 15 skills, the installer's output and the update line are
Russian text, because Russian is the language I write specs in. The agent
answers in whatever language its owner writes in, and nothing in the scripts,
the layout or the link resolution is tied to a language — but open a skill to
see what it does and you will be reading Russian.

Loft replaced specos: I retired that setup in June 2026 after finally working
out why it kept "getting dumber" on ordinary markdown work. The overhead was
eating the context — two MCP servers markdown work never used, at 20–30k
tokens of schemas per session and per subagent, per-task ceremony, and an
early auto-compact throwing away what the session already knew. From the
chair, that is plain amnesia. Loft's always-on footprint is one contract of
about 3k tokens, with no MCP servers, vector indexes or daemons of its own.
The post-mortem — including what was measured and what wasn't — is in
[why-loft](docs/en/why-loft.md).

## Quickstart

**1.** Download `loft_1.3.5.tgz` and `loft_1.3.5.tgz.sha256` from
[Releases](https://github.com/bogdanov-igor/loft/releases/latest) into your
project folder.

**2.** Open the project in Claude Code and say:

> Install loft from the archive in this folder: verify the sha256, unpack it,
> run `loft/install.sh`, then tell me what it set up.

**3.** If the project ran specos before, add:

> Clean up the specos leftovers and propose the re-audit.

### Or do it yourself

```sh
cd /path/to/project                    # tgz + .sha256 copied here
shasum -c loft_1.3.5.tgz.sha256        # integrity first: expect "OK"
tar -xzf loft_1.3.5.tgz
bash loft/install.sh                   # no argument = install right here
```

From the source repo instead: `bash install.sh /path/to/project`.

Updating is the same command: newer loft, `install.sh` again. Kernel files are
replaced, project state is never touched, and the skills, agents and Claude
Code settings you added yourself are carried over. A `SessionStart` hook prints
one line when a newer loft sits next to the project (a `loft/` folder,
`$LOFT_HOME`) or in
[Releases](https://github.com/bogdanov-igor/loft/releases): cached for 24h, 3s
ceiling, and any failure exits quietly.

Dependencies: `python3` (all kernel scripts are stdlib); `pandoc` for the
`ingest-confluence`, `ingest-docs`, `review-intake` and `deliver-pdf` skills;
`lxml` for `ingest-confluence` alone.

## Who we write for

The headline change in 1.3.0. Documents used to be written, quietly, for
acceptance: "decision of 12.08" markers, "(Assumption)" tags, "see section 4"
footnotes — what an author uses to prove himself right to a judge. The person
who actually reads the document has opened no other files and is going to act
on it.

The clean copy is now written for him alone. Connected prose about what this
is and how it works; rules as short sentences shaped "input → case a: action →
case b: action"; the first sentence of a section carrying its point; a fact
stated once, and instead of a repeat a `[[wikilink]]` on the term itself, not
a footnote.

Everything procedural moved into the **document passport** — the frontmatter:
`status`, `source` (the request), `based_on` (files read in full),
`assumptions` (what was taken on trust and what would confirm it), `decisions`
(entries in `spec/решения.md`), `questions`. Substantiation is checked against
the passport; the clean copy never tells the reader who decided what, when or
why.

## What's inside

- The contract, [`.claude/CLAUDE.md`](bundle/.claude/CLAUDE.md): 149 lines, ~3k
  tokens — the only thing always in context: the profession, who we write for,
  pointers to the rest. Procedures live in skills and load when used. The core
  rule is right there: no invented facts — a claim either follows from a source
  or is named as an assumption in the passport.
- 15 lazily loaded skills.

  Spec work:
  - `tz-write` — write a spec or a section in the project's structure and voice.
  - `tz-adapt` — take a foreign structure's profile from samples and write in it.
  - `tz-elicit` — turn an incomplete request into a brief: question banks for 6
    task types, phrasing templates, a self-check for waffle.
  - `tz-audit` — check a document or the corpus along seven axes, findings into `BACKLOG.md`.
  - `spec-bootstrap` — stand up a new project's docs: layout, structure profile,
    glossary, decision register.

  Corpus:
  - `ingest-confluence` — turn a Confluence HTML export into an md wiki with `[[wikilinks]]`.
  - `ingest-docs` — pull docx/pdf/html/images out of `inbox/`, processed originals to `inbox/done/`.
  - `link-check` — find broken `[[wikilinks]]`, `![[embeds]]`, md links and orphans.
  - `knowledge-map` — build `wiki/_KNOWLEDGE-MAP.md`: domains, entry points, a line per page.
  - `review-intake` — turn an edited docx or edits pasted as text into an accept/reject/question table.

  Process and delivery:
  - `stage` — run big work: a brief with readiness criteria before, a verified report after.
  - `remember` — file a lesson, antipattern, pattern or structure profile into memory.
  - `deliver-pdf` — build a PDF through a chain of engines, or the `.md` bundle for NotebookLM.
  - `claude-docs` — publish a claude.ai page, on a direct command only.
  - `migrate-specos` — move the predecessor's machinery into quarantine with a rollback manifest.
- Two subagents, both purely for context isolation. `scout` reads page batches
  on Sonnet so the main window stays clean, and reports what it opened in full
  and what it only saw in fragments. `verifier`, in a fresh context, judges big
  work and anything delivered outside the corpus — against the readiness
  criteria from the brief and through the reader's eyes, two rounds of fixes.
  Small work the author checks himself: ceremony on trifles is a pure tax.
- Three hooks. `leak-guard` keeps values from `.secrets.env` out of documents
  (the rest of the hygiene — IPs, hosts, credentials in the clear — is on the
  agent and the "hygiene" axis in `tz-audit`), a silent update check, and
  `stage-brief`, which after a compact reminds you of an open stage in one line.
- Memory is files: notes under `memory/` with a one-line index, `BACKLOG.md` as
  the single work queue, `QUESTIONS.md` carrying a resume plan for every open
  stakeholder question.
- The `analyst` output style — optional, via `/config` → Output style: it lifts
  the instructions about writing code, kernel tools get run as given, and a
  broken script is a finding for the owner, not a task to go fix.

## What it leaves out

- No MCP servers by default, no vectors, no embeddings, no Ollama. specos
  seeded serena and playwright into every project unconditionally, and when the
  local embedding daemon was down, degraded search looked like amnesia.
- No RAG either — a decision, not a to-do. A corpus of a few hundred pages runs
  to a million tokens and will never be read whole, so the answer is found by
  map instead of by chunk: `wiki/_KNOWLEDGE-MAP.md` says which domain holds it,
  and `scout` reads that domain in full on Sonnet with a 1M window. A chunk
  without its context and caveats costs a spec more than the extra reading does.
- No per-task ceremony: no runs log, no schema validation, no multi-gate verify
  on every touch. Small work (one page, low risk) leaves no process files
  behind; big work (a full spec, an audit, a restructuring) leaves exactly two:
  `stages/NNN-slug/brief.md` before and a verified `report.md` after.
- No patching of other people's extensions: diagrams are stored as `mermaid`
  fences and render wherever the corpus is read.
- No auto-sync with NotebookLM: the link runs one way. `deliver-pdf` builds an
  `.md` bundle or a PDF for a corpus domain, and answers and summaries come back
  through `inbox/`. The kernel ships no MCP server for it and no library built
  on cookies and undocumented APIs: those break quietly and take your trust in
  the notebook's contents with them.

The boundary rule, from the roadmap: a script in the kernel can only be a
deterministic data converter, input in and output out — `convert.py` (with
`tablemd.py` inside it, shared with `fix_tables.py`), `make_index.py`,
`fix_tables.py`, `link_check.py`, `export_pdf.py`, `sweep.sh`. Checks of meaning
are written as instructions to agents in skills. Anything with state, history
or a UI belongs outside the kernel.

## The Confluence converter

The skill `ingest-confluence` turns a Confluence HTML space export into a
markdown wiki with `[[wikilinks]]`. The conversion is deterministic (pandoc +
lxml); no LLM touches the content on the way through.

- Tables go HTML→GFM through the converter's own writer. What GFM can't express
  stays HTML and is logged with the reason — nothing is mangled silently.
- Attachment links get their names back from the export's
  `data-linked-resource-default-alias` attribute instead of `download.xhtml?...`.
  Attribute noise (`class`/`style`/`rel`/`data-*`) is scrubbed before pandoc, so
  a link comes out as `[text](url)` → `[[wikilink]]` rather than raw
  `<a class=...>`; Jira avatars and emoticons are dropped.
- Colour that carries meaning survives: a non-default text colour or a
  highlighted cell comes out as `<span style="color:#hex">`, the theme's own
  colours are dropped. A link Confluence failed to render keeps its words, an
  inline `data:` picture becomes a file in `assets/`, markdown typed by hand in
  the editor becomes one link, and a relative link out of the export gets its
  host from `--base-url`.
- Re-running the ingest updates the snapshot: stale pages are removed (files
  without a `confluence_id` never are, and a mass removal is blocked until you
  say `--allow-mass-removal`), and you get a change report —
  `wiki/_CHANGES-<date>.md` for people, `wiki/.ingest.json` for scripts.
- `--unroll-pre` unrolls tables holding multi-line JSON/XML examples into plain
  GFM, moving the code below the table as fenced blocks, byte for byte.
  `--expand-spans` does the same for merged cells: rowspan repeats the value,
  colspan pads with empty ones — layout loss, never data loss.
- `--space` and `--base-url` open any space and the snapshot date comes from
  the export itself; `fix_tables.py` upgrades v1-converted wikis in place,
  idempotently.

Numbers from the corpus the converter was built against, a banking wiki: 336
pages out of the export plus hand-written layers on top. 468 of 609 raw HTML
tables came out as clean GFM (the rest are logged fallbacks, nearly all
multi-line JSON examples), 0 empty links, all 336 pages byte-identical to the
reference conversion, 0 broken links out of 3,645 across the whole tree under
`link-check`.

## The corpus is a graph

The corpus speaks the Foam/Obsidian dialect on purpose: `[[wikilinks]]`
resolved by basename, `![[embeds]]`, `\|`-escaped aliases in tables. Open the
project folder in [Obsidian](https://obsidian.md), or install
[Foam](https://foambubble.github.io/foam/) in VS Code (the installer seeds the
extension recommendation), and the graph view, backlinks and link navigation
just work. `link-check` resolves links the same way (basename,
case-insensitive, NFC): green means the graph has no holes.

## Tests

`test/run.sh` is a thin harness plus `test/cases/*.sh` by area: bundle
integrity, `link_check`, the table writer, `fix_tables`, the migration sweep,
`leak-guard`, the update check, the converter, the PDF exporter, installer
scenarios. Over 500 self-tests, all offline, against throwaway fixtures.
`build-archive.sh` holds them as a release gate and then installs loft from the
freshly built archive into a temp directory. The 0.1.0 release also went
through an independent review: 20 findings, all closed, the 3 critical ones in
code inherited from the v1 converter.

## Layout in a deployed project

```text
.claude/      kernel (kernel-owned: reinstalling overwrites it)
wiki/         Confluence mirror — generated, never edited by hand
spec/         specs · _STRUCTURE.md (structure and voice) · решения.md ·
              _reference/ (samples) · _reviews/ (decisions on returns)
inbox/        incoming files before conversion; processed ones go to inbox/done/
memory/       project memory: MEMORY.md index + lessons/antipatterns/patterns/structures
stages/       big-work artifacts: NNN-slug/brief.md + report.md
BACKLOG.md    the one canonical work queue
QUESTIONS.md  open stakeholder questions, each with a resume plan
```

## Coming from specos?

Install loft, then run the `migrate-specos` skill: the predecessor's machinery
(bundles, distributions, engine state) moves into the quarantine
`.loft-migration/<timestamp>/` with a restore manifest. Nothing is deleted, and
project state — wiki, specs, memory, backlog — is never touched. The MCP tax
stops travelling at install time already: a specos-era `.mcp.json` goes to
backup, not into your next session. Details in the
[migration guide](docs/en/migration.md).

## Documentation

| | English | Русский |
|---|---|---|
| Install & update | [install](docs/en/install.md) | [установка](docs/ru/install.md) |
| Architecture | [architecture](docs/en/architecture.md) | [архитектура](docs/ru/architecture.md) |
| Migrating from specos | [migration](docs/en/migration.md) | [миграция](docs/ru/migration.md) |
| What changed, measured | [why-loft](docs/en/why-loft.md) | [почему loft](docs/ru/why-loft.md) |

## Licence

[Apache-2.0](LICENSE) © 2026 **Igor Bogdanov** · <bogdanov.ig.alex@gmail.com>

Free to use, fork and build on, commercially included. Keep the attribution and
note what you changed.
