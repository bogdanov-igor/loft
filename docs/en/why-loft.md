# Why Loft, and what changed from specos

Loft is the successor to specos: same author, same profession, opposite
conclusion. specos tried to give a document-working agent a whole system —
two MCP servers seeded into every project, an embedding index over memory, a
run log, schema-validated artifacts, a multi-gate verify, even a patched
webview in a third-party extension to render diagrams. What I got was a setup
that demonstrably "got dumber" the longer it ran. Loft keeps the profession
and drops the system.

I retired specos in June 2026. This document is the post-mortem: what was
actually observed, what loft does about each cause, and — just as important —
what was never measured.

## The symptom

"It's gotten dumb. It loses context." That was the complaint. The natural
suspects, the model and the contract file, turned out to be innocent; the
always-on instructions were never the problem. The problem was everything
loaded and executed around them.

## The diagnosis

### 1. The MCP tax

specos seeded `serena` and `playwright` unconditionally into every project's
`.mcp.json`. Their tool schemas cost about 20–30k tokens per session, and
then again per subagent, because each subagent loads the schemas anew. For a
profession whose entire workspace is markdown files, an LSP for code symbols
and a browser-automation server are dead weight — a tax paid on every single
interaction that bought nothing.

Loft ships zero MCP servers. A corpus of a few hundred markdown pages is
found by reading a one-line index and grepping. The always-on load is one
contract, ~3k tokens, roughly 8–10× less than the schema tax alone. The
installer goes one step further and moves a specos-era `.mcp.json` to backup,
so the tax doesn't survive the migration out of inertia.

### 2. Ceremony on every task

Under specos, every task — a full spec and a one-line correction alike —
walked the same pipeline: append to `runs.jsonl`, `memory_search`, schema
validation of artifacts, a `verify` pass with 9+ gates, lesson, embed. Every
step produced tool output, and tool output is context. The dialog filled up
with machinery instead of work, auto-compact fired early, and the compacted
session had genuinely lost what it knew. In other words, the ceremony was
manufacturing the very amnesia it was supposed to prevent.

Loft has two tiers of work instead. Small work (one page, low risk): do it,
check it, move on, no process files. Big work (a full spec, a corpus audit, a
restructuring): the `stage` skill, exactly two files — `stages/NNN-slug/brief.md`
before, a verifier-confirmed `report.md` after.

### 3. Memory that needed a daemon

specos memory had no pruning, and retrieval ran on embeddings served by a
local Ollama. Whenever Ollama was down or degraded, search quietly degraded
with it. To the person in the chair, degraded retrieval is indistinguishable
from a system that forgot things — so it looked like amnesia and got
diagnosed as "getting dumber".

Loft's memory is files: markdown notes plus a strict one-line index
(`memory/MEMORY.md`). Retrieval is reading the index and grepping. There is
no embedding model, no vector store, and no daemon whose silent failure can
masquerade as memory loss.

### 4. The patched webview

To render diagrams, specos patched the webview of a third-party extension —
3.1 MB of vendored JavaScript riding along in the bundle. Every upstream
update of that extension could break the patch, and eventually did.

In loft, diagrams are the consumer's concern. The corpus stores `mermaid`
fences; whatever reads the corpus renders them. Loft ships no renderer,
patches nothing, vendors nothing.

## What loft is instead

One always-on contract (81 lines, ~3k tokens) stating the profession and the
pointers. 14 skills that load only when used. 2 subagents, split by context
isolation rather than job title. 2 hooks. File memory with a one-line index.
Zero runtime services. The profession's core rule sits in the contract
itself: no invented facts — every claim is derivable from a source or
explicitly marked as an assumption or a question. And the boundary rule keeps
the kernel from growing back into a system: a script in the kernel may only
be a deterministic data converter, checks of meaning are instructions to
agents, and anything with state, history or UI lives outside the kernel.

## What has actually been checked

The claims above are structural: less loaded, fewer moving parts. Two things
were checked against reality.

- The converter ran on a real banking corpus of 446 pages. 468 of 609 raw
  HTML tables converted to clean GFM (the remainder are logged fallbacks with
  reasons, almost all multi-line JSON examples), 0 empty links, a 336-page
  tree byte-identical to the reference conversion, 0 broken links out of
  3,645. Because the conversion is deterministic — pandoc + lxml, no LLM
  rewriting facts — "byte-identical" is a statement you can actually verify.
- The 0.1.0 release went through an independent review: 20/20 findings
  closed, the 3 critical ones in code inherited from the v1 converter. The
  kernel's own `test/run.sh` (the release gate for `build-archive.sh`) pins
  those cases so they don't come back.

## What was NOT measured

Spelled out so the comparison doesn't oversell itself:

- The token figures are estimates. "~20–30k" is the observed order of the
  schema load and "~3k" the order of the contract; neither comes from running
  a tokenizer over a controlled session, and "8–10×" is just the ratio of the
  two estimates.
- There was no head-to-head benchmark. Nobody ran a fixed suite of analyst
  tasks under both kernels and compared tokens, wall-clock and quality. The
  degradation story above is a production diagnosis with named mechanisms,
  not a controlled experiment.
- "Better" here means less to load, less to trust, less to break. It does not
  mean "writes better specs" — that claim would need the benchmark, which
  hasn't been run.

What does hold: loft loads roughly 8–10× less always-on weight, needs zero
runtime services where specos needed an MCP host and an embedding daemon,
produces no process files on small work where specos demanded the full
pipeline, and contains no component whose silent failure looks like amnesia.

---

**Author:** Igor Bogdanov · <bogdanov.ig.alex@gmail.com>
