# Why Loft, and what changed from specos

Loft is the successor to specos — same author, same profession, opposite
conclusion. specos tried to give a document-working agent a *system*: two MCP
servers seeded into every project, an embedding index over memory, a run log,
schema-validated artifacts, a multi-gate verify, even a patched webview in a
third-party extension to render diagrams. The result was a setup that
demonstrably "got dumber" the longer it ran. Loft keeps the profession and
deletes the system.

specos was buried in June 2026. This document states the diagnosis — what was
actually observed, cause by cause — what loft does against each cause, and,
importantly, **what was not measured**.

## The symptom

"It's gotten dumb. It loses context." That was the complaint, and the natural
suspects — the model, the contract file — were innocent. The always-on
instructions were never the problem. The problem was everything loaded and
executed *around* them.

## The diagnosis, cause by cause

### 1. The MCP tax

specos seeded `serena` and `playwright` unconditionally into every project's
`.mcp.json`. Their tool schemas cost **~20–30k tokens on every session — and
again on every subagent**, because each subagent loads the schemas anew. For a
profession whose entire workspace is markdown files, an LSP for code symbols
and a browser-automation server are dead weight: a recurring tax paid on every
single interaction, buying nothing.

**Against it:** loft ships **zero MCP servers**. A corpus of a few hundred
markdown pages is found by reading a one-line index and grepping. The always-on
load is one 79-line contract, ~3k tokens — roughly **8–10× less** than the
schema tax alone. The installer goes further: a specos-era `.mcp.json` is moved
to backup, so the tax does not survive the migration by inertia.

### 2. Ceremony on every task

Under specos, every task — a full spec and a one-line correction alike — walked
the same pipeline: append to `runs.jsonl` → `memory_search` → SCHEMA validation
of artifacts → a `verify` pass with 9+ gates → lesson → embed. Every step
produced tool output, and tool output is context. The dialog filled with
machinery instead of work, auto-compact fired early, and the compacted session
had genuinely lost what it knew. The ceremony *manufactured* the very amnesia
it was meant to prevent.

**Against it:** two tiers of work. Small work (one page, low risk): do it,
check it, move on — zero process files. Big work (a full spec, a corpus audit,
a restructuring): skill `stage`, exactly two files — `stages/NNN-slug/brief.md`
before, a verifier-confirmed `report.md` after. That is the whole ceremony
budget.

### 3. Memory that needed a daemon

specos memory had no pruning, and retrieval ran on embeddings served by a
local Ollama. When Ollama was down or degraded — a local daemon, so a matter
of *when* — search quietly degraded with it. To the person in the chair,
degraded retrieval is indistinguishable from a system that forgot: it looked
like amnesia and was diagnosed as "getting dumber".

**Against it:** file memory with a strict one-line index (`memory/MEMORY.md`),
written and read as plain markdown. Retrieval is reading the index and
grepping. There is no embedding model, no vector store, no daemon whose
silent failure can masquerade as memory loss.

### 4. The patched webview

To render diagrams, specos patched the webview of a third-party extension —
3.1 MB of vendored JavaScript riding along in the bundle. Every upstream
update of that extension could break it, and did. A kernel that patches
someone else's binary artifact has signed up for someone else's release
schedule.

**Against it:** diagrams are the consumer's concern. The corpus stores
`mermaid` fences; whatever reads the corpus renders them. Loft ships no
renderer, patches nothing, and vendors nothing.

## What loft is instead

One always-on contract (81 lines, ~3k tokens) stating the profession and the
pointers; 14 skills that load only when used; 2 subagents split by context
isolation, not job title; 2 hooks; file memory with a one-line index; zero
runtime services. The profession's core rule sits in the contract itself:
**not a single invented fact** — every claim is derivable from a source or
explicitly marked as an assumption or a question. And the boundary rule keeps
the kernel from growing back into a system: a script in the kernel may only be
a deterministic data converter; checks of meaning are instructions to agents;
anything with state, history or UI lives outside the kernel.

## What is demonstrated, not promised

The claims above are structural — less loaded, fewer moving parts. Two things
have been checked against reality:

- **The converter, on a real banking corpus of 446 pages:** 468 of 609 raw
  HTML tables converted to clean GFM (the remainder are logged fallbacks with
  reasons, almost all multi-line JSON examples), 0 empty links, a 336-page
  tree byte-identical to the reference conversion, 0 broken links out of
  3,645. Deterministic conversion — pandoc + lxml, no LLM rewriting facts —
  is what makes "byte-identical" a checkable statement at all.
- **Independent verification of the 0.1.0 release:** 20/20 findings closed;
  the 3 critical ones were in code inherited from the v1 converter. The
  kernel's own `test/run.sh` (29+ self-tests, the release gate for
  `build-archive.sh`) pins those cases so they cannot come back.

## What was NOT measured

Stated plainly, because a comparison that hides its gaps is marketing:

- **The token figures are estimates.** "~20–30k" is the observed order of the
  schema load, "~3k" the order of the contract; neither comes from running a
  tokenizer over a controlled session, and "8–10×" is the ratio of those
  estimates.
- **No head-to-head task benchmark was run.** No fixed suite of analyst tasks
  was executed under both kernels with tokens, wall-clock and quality
  compared. The degradation account above is a production diagnosis with
  named mechanisms — not a controlled experiment.
- **"Better" here means: less to load, less to trust, less to break.** It does
  not mean "writes better specs" — that claim would need the benchmark, and
  it has not been run.

What *is* established: loft loads roughly 8–10× less always-on weight, needs
zero runtime services where specos needed an MCP host and an embedding daemon,
produces zero process files on small work where specos demanded the full
pipeline, and contains no component whose silent failure looks like amnesia.

---

**Author:** Igor Bogdanov · <bogdanov.ig.alex@gmail.com>
