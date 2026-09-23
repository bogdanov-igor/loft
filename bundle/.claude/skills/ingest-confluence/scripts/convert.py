#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Confluence HTML space export  ->  Markdown knowledge base (wiki/) with wikilinks.  v2
Deterministic: lxml for DOM cleanup of Confluence macros, pandoc for HTML->GFM,
regex post-processing for [[wikilinks]] and ![[asset]] embeds.

v2 changes (vs v1):
- tables are converted by our own writer (tablemd.py: HTML -> GFM pipe table),
  not by pandoc; raw-HTML fallback ONLY for colspan/rowspan, nested tables and
  long/indented <pre> in cells -- each fallback is logged ([table-fallback]);
- empty attachment anchors (<a ...></a>, Confluence file-cards) get their text
  from data-linked-resource-default-alias / aria-label / basename(href) in
  clean_dom, before pandoc -- both inside and outside tables;
- "|" inside [[wikilinks]] on pipe-table rows is escaped as "\\|" so generated
  links never break the table grid;
- table placeholders are re-inserted with the surrounding indentation (tables
  inside list items stay inside their list items);
- project-agnostic: --space (default: export dir name) and --base-url (default:
  empty -> no source:/footer Confluence links) instead of hardcoded values;
  space name + snapshot date go to <out>/.space.json for make_index.py;
- re-ingest into the same dir removes pages that vanished from the export
  ([stale-removed]); files without confluence_id frontmatter are never touched;
- pandoc failures raise (no silent empty pages);
- change report: .pagemap.json entries carry a sha1 of the page content; a
  re-ingest (previous .pagemap.json existed) diffs against it and writes a human
  wiki/_CHANGES-<snapshot>.md (added/changed/moved/removed + spec/ impact);
  machine-readable wiki/.ingest.json is written on EVERY run.

v2.1 changes:
- run parameters (converter version, hash algo, --unroll-pre/--expand-spans) are
  persisted to .space.json; a re-ingest with other flags warns loudly and stamps
  the _CHANGES header -- "changed" is then not to be trusted;
- the "changed" hash covers the page body only (no frontmatter, breadcrumbs or
  footer), so --base-url or a renamed sibling no longer marks pages changed;
- stale removal only touches pages whose frontmatter `space:` is THIS space, and
  refuses a mass wipe (a partial export) without --allow-mass-removal;
- links to pages outside the export are logged ([link-miss]) and listed in
  .ingest.json; #anchors survive as [[page#anchor]];
- code fences are masked during post-processing (link/cleanup rules used to
  rewrite example code);
- sized images become ![[embeds]] (size dropped) instead of raw <img>;
- info/note/warning panel titles, text right after </table> and tables inside
  list items are no longer lost/broken;
- the snapshot date falling back to mtime is reported (snapshot_date_source).

v2.2 changes:
- anchor TARGETS survive: <a name>/<a id> keep their attributes, and the
  Confluence anchor macro (<span class="confluence-anchor-link" id="X">) is
  materialized as <a name="X"></a>. pandoc rewrites an empty <a name> into
  <span id>, so anchors are masked as plain-text tokens for the pandoc AND the
  table pass and restored as raw inline HTML afterwards -- without this the
  [[page#anchor]] links of 2.1 point at nothing. An anchor sitting inside a
  heading is hoisted to its own line before it: heading text is what a
  [[page#Heading]] link resolves against, and raw HTML glued to it breaks that;
- .space.json carries a per-space dict `spaces` (name, snapshot_date, pages)
  next to the current space's own fields: one wiki may hold several spaces, and
  make_index.py groups Home.md by space instead of turning the roots of a
  foreign space into extra roots of the current one.

v2.3 changes:
- a link to an anchor of the SAME page ([text](#id-...), percent-encoded by
  pandoc) becomes [[#anchor|text]] -- the Obsidian/Foam form of a link inside
  the current note -- with the anchor decoded and spelled exactly like the
  <a name> target 2.2 keeps. An anchor that exists on no <a name> of the page
  (a typo in Confluence, a truncated anchor name) degrades to plain text and is
  logged [link-miss], like a link to a page outside the export;
- an ABSOLUTE link to another page keeps its fragment too: ...pageId=N#frag,
  /spaces/KEY/pages/N/...#frag and /display/KEY/Title#frag resolve to
  [[page#anchor|text]], not to [[page]] -- the reader used to land on the top
  of a long page instead of the named section;
- .space.json names the snapshot date `snapshot_date` at the top level as well
  (it was `snapshot` there and `snapshot_date` inside `spaces`); the old name is
  still read, so a wiki ingested by an earlier version keeps its date.

v2.4 changes:
- anchor links NAVIGATE in Obsidian/Foam. Those renderers resolve `#fragment`
  against heading text and against block ids (`^id`) -- never against an
  <a name>, so every [[page#id-...]] of 2.3 led nowhere. Each anchor target is
  now classified by where it sits and links to it are written in the form that
  actually jumps there:
    * anchor in a heading (the Confluence anchor macro glued into it) ->
      [[page#Текст заголовка|text]] / [[#Текст заголовка|text]], the heading
      text as it stands in the md (markup stripped, and #|[]^ removed the way
      Obsidian strips them). The <a name> line before the heading stays -- the
      HTML/PDF export resolves by it;
    * anchor in a paragraph -> a block id ` ^a-<8 hex of sha1(name)>` is
      appended to that paragraph next to the <a name>, and links become
      [[page#^a-xxxxxxxx|text]]. Two anchors in one paragraph share its block
      id (a block has only one);
    * anchor in a table cell -> the #id form of 2.3, unchanged: a block id
      inside a cell resolves nowhere and a cell has no heading text. Honestly
      unreachable in Obsidian, reachable in HTML/PDF by the <a name>;
  a fragment matching no anchor of the target page keeps the 2.3 behaviour --
  on the same page it degrades to text and is logged [link-miss], on another
  page it is left as written (the page link still works);
- pages are converted in two passes for that: bodies + anchor maps first, link
  rewriting after -- a link from page A to an anchor of page B needs B's map.

v2.5 changes:
- a link Confluence could not render (<img class="transform-error"
  data-encoded-xml="..."> holding an <ac:link>) keeps its text: the link body
  (ac:link-body / ac:plain-text-link-body, else the page title) is emitted, as
  a [[wikilink]] when ri:content-title is a page of this export, else as plain
  text logged [link-miss]. Such links used to vanish WITH their words. Other
  placeholders are dropped as before;
- non-default text colour and highlight survive as inline HTML:
  <span style="color:#rrggbb">...</span> / background-color. CSS vars resolve to
  their (innermost) fallback hex, rgb() -> hex. Default text colour (var(--ds-
  text,...), #172b4d, #333333, #000000) and neutral backgrounds (--ds-surface,
  gray-subtlest, #ffffff, #f4f5f7, #f1f2f4) are not colour. Colour is applied
  to inline runs only (never across a block, never inside code/pre); a heading
  is painted inside its "#" line ([[page#Heading]] is matched against its text
  with HTML stripped). Code without the run's colour in the source breaks the
  run. A coloured link is wrapped whole; a link only partly coloured is split
  into one link per colour stretch of its label (same target), each wrapped
  whole. Only when the label cannot be split at its top level (a child of
  mixed colour, a block inside) the link stays unpainted and each coloured
  piece is logged [colour-lost] (.ingest.json colour_lost). Whitespace-only
  text is never wrapped. A coloured table
  cell: GFM -> span around the cell content, raw-HTML fallback -> style on the
  td/th. Colour travels through pandoc and tablemd as plain-text tokens, like
  anchors;
- "[label](" typed in Confluence right before a link and ")" right after it
  (markdown written by hand in the editor) become ONE link with that label.
  Checked twice: on the source (a ")" after the <a>) and on the markdown (a
  ")" right after the link as it stands after the link rules -- a link to a
  page whose title ends in ")" leaves its own ")" there). Bracket text in any
  other shape (no ")" after the link) is left as written;
- inline data: URI images are decoded into assets/<pageid>_inline_<sha1[:10]>.
  <ext> and embedded like any other picture -- a data: URI is never emitted;
- a relative Confluence link (/pages/, /display/, /spaces/, /x/, /download/)
  that resolves to nothing in the export becomes absolute with --base-url
  (without it: plain text + [link-miss], in raw-HTML tables too; createpage
  redlinks collapse to text silently, as before);
- a re-ingest by another converter version is warned about like changed flags:
  "changed" then includes pages the new converter renders differently.
"""
import os, re, sys, html, json, base64, zlib, shutil, subprocess, argparse
import hashlib, unicodedata
import urllib.parse
from collections import OrderedDict
import lxml.html
from lxml import etree
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tablemd

# printing Cyrillic must not depend on the shell locale (LC_ALL=C -> traceback)
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:                              # pragma: no cover - py<3.7 / pipes
        pass

CONVERTER_VERSION = "2.5"
# how rec["hash"] is computed. Bumping it makes "changed" meaningless against
# an older .pagemap.json -- that is reported, not silently diffed.
HASH_ALGO = "body-v1"
# stale removal guard: more than MASS_FRAC of the previous map (but at least
# MASS_MIN pages), or more than MASS_ABS pages, looks like a broken export
MASS_ABS, MASS_FRAC, MASS_MIN = 30, 0.2, 5

def die(msg, code=2):
    print(msg, file=sys.stderr)
    sys.exit(code)

_ap = argparse.ArgumentParser(description="Confluence HTML space export -> markdown wiki")
_ap.add_argument("src", help=".../confluence_raw/<SPACE> (contains index.html)")
_ap.add_argument("out", help="target wiki dir")
_ap.add_argument("--space", default="", help="space key (default: export dir name)")
_ap.add_argument("--base-url", default="",
                 help="Confluence base URL; empty -> no source:/footer links")
_ap.add_argument("--unroll-pre", action="store_true",
                 help="multiline <pre> in table cells -> 'см. Пример N ниже' + "
                      "fenced code blocks after the table (no multiline-pre fallback)")
_ap.add_argument("--expand-spans", action="store_true",
                 help="tables with colspan/rowspan -> GFM anyway: rowspan "
                      "repeats the value, colspan pads with empty cells "
                      "(no colspan-rowspan fallback)")
_ap.add_argument("--allow-mass-removal", action="store_true",
                 help="allow deleting a large share of the previously ingested "
                      "pages (a partial export otherwise wipes the wiki)")
_args = _ap.parse_args()
SRC = _args.src
OUT = _args.out
BASE_URL = _args.base_url.rstrip("/")
UNROLL_PRE = _args.unroll_pre
EXPAND_SPANS = _args.expand_spans
ALLOW_MASS_REMOVAL = _args.allow_mass_removal
# flags that change the BODY of generated pages -- persisted, so the next run
# can tell a real content diff from "you passed different flags this time"
RUN_FLAGS = {"unroll_pre": UNROLL_PRE, "expand_spans": EXPAND_SPANS}

def flags_str(f):
    if not isinstance(f, dict):
        return "неизвестно (прогон старым конвертером)"
    on = [name for name, k in (("--unroll-pre", "unroll_pre"),
                               ("--expand-spans", "expand_spans")) if f.get(k)]
    return " ".join(on) if on else "(без флагов)"

if not os.path.isdir(SRC):
    die(f"convert.py: каталога выгрузки нет: {SRC}")
if not os.path.exists(os.path.join(SRC, "index.html")):
    die(f"convert.py: в каталоге выгрузки нет index.html: {SRC}\n"
        "  нужен распакованный HTML-экспорт спейса Confluence "
        "(index.html + страницы NNN.html)")

def space_key_from_index(src):
    """Space key from the 'Key' row of index.html. The directory name is a
    weak default: `space:` in the frontmatter decides which pages a re-ingest
    is allowed to delete, and an export unzipped into 'tmp2' must not turn
    every page of the wiki into a foreigner."""
    try:
        raw = open(os.path.join(src, "index.html"), encoding="utf-8").read()
    except OSError:
        return ""
    m = re.search(r"<th[^>]*>\s*Key\s*</th>\s*<td[^>]*>(.*?)</td>", raw, re.S)
    key = html.unescape(re.sub(r"<[^>]+>", "", m.group(1))).strip() if m else ""
    return key if re.fullmatch(r"[A-Za-z0-9_.\-~]{1,64}", key or "") else ""

SPACE = (_args.space or space_key_from_index(SRC)
         or os.path.basename(os.path.normpath(SRC)))
LIMIT = int(os.environ.get("LIMIT", "0"))             # 0 = all
ONLY = set(filter(None, os.environ.get("ONLY", "").split(",")))  # ids to convert
VIEW = BASE_URL + "/pages/viewpage.action?pageId={id}" if BASE_URL else ""

ASSETS = os.path.join(OUT, "assets")
ATTACH = os.path.join(OUT, "attachments")

# ---------------------------------------------------------------- helpers
def slugify(title, maxlen=90):
    t = html.unescape(title).strip()
    t = t.replace("/", "-").replace("\\", "-")
    # drop filesystem-unsafe and wikilink-unsafe chars
    t = re.sub(r'[\x00-\x1f<>:"|?*\[\]#^]', "", t)
    t = t.replace("&", "and")
    t = re.sub(r"\s+", " ", t).strip()
    t = t.replace(" ", "-")
    t = re.sub(r"-{2,}", "-", t).strip("-. ")
    if len(t) > maxlen:
        t = t[:maxlen].rstrip("-. ")
    return t or "page"

def id_of(href):
    m = re.search(r"(\d+)\.html$", href)
    return m.group(1) if m else None

# ---------------------------------------------------------------- 1. page map
def build_map(src):
    idx = os.path.join(src, "index.html")
    raw = open(idx, encoding="utf-8").read()
    pages = OrderedDict()   # id -> record
    href2id = {}
    stack = []              # stack of ids by depth
    depth = 0
    order = 0
    for m in re.finditer(r"<ul>|</ul>|<a href=\"([^\"]+)\">(.*?)</a>", raw, re.S):
        tok = m.group(0)
        if tok == "<ul>":
            depth += 1
        elif tok == "</ul>":
            depth -= 1
            stack = stack[:depth]
        else:
            href, title = m.group(1), re.sub(r"<[^>]+>", "", m.group(2))
            title = html.unescape(title).strip()
            pid = id_of(href)
            if not pid:           # external link (atlassian.com) -> skip
                continue
            # Markup we parse: Confluence HTML export ("Available Pages:" list)
            # wraps EVERY subtree in its own <ul> -- siblings are separated by
            # </ul><ul>, so before each <a> the stack is already truncated to
            # the ancestor chain. stack[depth-2] is the parent BOTH for that
            # markup and for canonical nested lists (siblings sharing one <ul>,
            # where stack[-1] would wrongly point at the previous sibling).
            parent = stack[depth - 2] if depth >= 2 and len(stack) >= depth - 1 else None
            order += 1
            slug = slugify(title)
            rec = dict(id=pid, href=href, title=title, parent=parent,
                       depth=depth, order=order, slug=slug,
                       basename=f"{slug}-{pid}", children=[])
            pages[pid] = rec
            href2id[href] = pid
            href2id[os.path.basename(href)] = pid
            # maintain stack: position depth-1 holds current node for its children
            stack = stack[:depth - 1]
            stack.append(pid)
    # link children
    for pid, rec in pages.items():
        p = rec["parent"]
        if p and p in pages:
            pages[p]["children"].append(pid)
    # compute folder path (mirror tree). Root home page -> wiki root.
    root_id = next(iter(pages))   # first = Home
    def folder_for(pid):
        parts = []
        cur = pages[pid]["parent"]
        while cur and cur in pages and cur != root_id:
            parts.append(pages[cur]["slug"])
            cur = pages[cur]["parent"]
        return list(reversed(parts))
    for pid, rec in pages.items():
        if pid == root_id:
            rec["relpath"] = rec["basename"] + ".md"
        else:
            folder = folder_for(pid)
            rec["relpath"] = os.path.join(*folder, rec["basename"] + ".md") if folder else rec["basename"] + ".md"
    pages[root_id]["is_home"] = True
    return pages, href2id, root_id

# ---------------------------------------------------------------- 1b. space metadata
_MONTHS = {  # Confluence footer date, ru/en locale abbreviations -> month no.
    "янв": 1, "фев": 2, "мар": 3, "апр": 4, "мая": 5, "май": 5, "июн": 6,
    "июл": 7, "авг": 8, "сен": 9, "окт": 10, "ноя": 11, "дек": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

def parse_space_meta(src):
    """Space name + export date from index.html (deterministic from input).
    Date: 'Document generated by Confluence on <date>' footer; fallback --
    newest mtime among the export's *.html (mtime is NOT the snapshot date:
    unzipping can rewrite it, so the fallback is loud and recorded).
    -> (name, snapshot, source) where source is footer|mtime|none."""
    raw = open(os.path.join(src, "index.html"), encoding="utf-8").read()
    name = ""
    m = re.search(r"<th[^>]*>\s*Name\s*</th>\s*<td[^>]*>(.*?)</td>", raw, re.S)
    if m:
        name = html.unescape(re.sub(r"<[^>]+>", "", m.group(1))).strip()
    snapshot = ""
    m = re.search(r"Document generated by Confluence on\s*([^<]+)", raw)
    if m:
        dm = re.search(r"([^\W\d_]+)\.?\s+(\d{1,2}),\s*(\d{4})", m.group(1), re.U)
        if dm:
            mon = _MONTHS.get(dm.group(1)[:3].lower())
            if mon:
                snapshot = f"{int(dm.group(3)):04d}-{mon:02d}-{int(dm.group(2)):02d}"
    if snapshot:
        return name, snapshot, "footer"
    mt = [os.path.getmtime(os.path.join(src, f)) for f in os.listdir(src)
          if f.endswith(".html")]
    if mt:
        import datetime
        snapshot = datetime.date.fromtimestamp(max(mt)).isoformat()
        print("[warn] дату снапшота не удалось разобрать из подвала index.html "
              f"('Document generated by Confluence on ...') — взята из mtime файлов "
              f"выгрузки: {snapshot}. Проверь дату вручную, она попадёт в Home.md "
              "и в имя _CHANGES.", file=sys.stderr)
        return name, snapshot, "mtime"
    print("[warn] дату снапшота определить не удалось: ни подвала index.html, "
          "ни html-файлов с mtime", file=sys.stderr)
    return name, "", "none"

# ---------------------------------------------------------------- 2. macro cleanup (lxml)
BRUSH = {
    "js": "javascript", "javascript": "javascript", "java": "java", "json": "json",
    "xml": "xml", "html": "html", "sql": "sql", "bash": "bash", "shell": "bash",
    "py": "python", "python": "python", "php": "php", "c": "c", "cpp": "cpp",
    "csharp": "csharp", "c#": "csharp", "yaml": "yaml", "yml": "yaml", "css": "css",
    "groovy": "groovy", "properties": "properties", "ruby": "ruby", "go": "go",
    "kotlin": "kotlin", "text": "", "plain": "", "none": "", "applescript": "",
}
INFO_STYLE = {
    "information": ("ℹ️", "Инфо"), "tip": ("✅", "Совет"),
    "note": ("📝", "Заметка"), "warning": ("⚠️", "Внимание"),
}
HEADINGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
LOZENGE_EMOJI = {"error": "🔴", "success": "🟢", "moved": "🟡", "current": "🔵", "complete": "🟢", "": "⚪"}
KEEP_ATTRS = {   # clean_dom 6c: everything not whitelisted is scrubbed
    # title survives in [t](u "title"); name/id are anchor TARGETS -- scrubbing
    # them left every [[page#anchor]] link pointing at nothing
    "a": ("href", "title", "name", "id"),
    # NO width/height: pandoc renders a sized <img> as raw HTML, which is
    # invisible to link-check and to Obsidian's embed resolution. Size is
    # traded for a real ![[embed]].
    "img": ("src", "alt"),
    "td": ("colspan", "rowspan"), "th": ("colspan", "rowspan"),
    "pre": ("class",), "code": ("class",),       # language-... for fences
}

def E(tag, text=None):
    el = etree.Element(tag)
    if text is not None:
        el.text = text
    return el

def replace_with(old, new_el, keep_tail=True):
    parent = old.getparent()
    if parent is None:
        return
    if keep_tail and old.tail:
        new_el.tail = (new_el.tail or "") + old.tail
    parent.replace(old, new_el)

def unwrap(el):
    """remove el, promoting its children into its place"""
    parent = el.getparent()
    if parent is None:
        return
    idx = list(parent).index(el)
    children = list(el)
    # text handling
    prev_text = el.text or ""
    if children:
        # attach el.text to first child's preceding sibling text
        if idx == 0:
            parent.text = (parent.text or "") + prev_text
        else:
            prev = parent[idx - 1]
            prev.tail = (prev.tail or "") + prev_text
        for i, c in enumerate(children):
            parent.insert(idx + i, c)
        # tail of el
        if el.tail:
            children[-1].tail = (children[-1].tail or "") + el.tail
    else:
        txt = prev_text + (el.tail or "")
        if idx == 0:
            parent.text = (parent.text or "") + txt
        else:
            prev = parent[idx - 1]
            prev.tail = (prev.tail or "") + txt
    parent.remove(el)

def insert_text_before(el, text):
    """put a text node right before el (parent.text or previous sibling's tail)"""
    parent = el.getparent()
    if parent is None:
        return
    i = list(parent).index(el)
    if i == 0:
        parent.text = (parent.text or "") + text
    else:
        parent[i - 1].tail = (parent[i - 1].tail or "") + text

def drop_to_text(el, text):
    """replace el (with its subtree) by a plain text node, keeping el's tail"""
    parent = el.getparent()
    if parent is None:
        return
    insert_text_before(el, text + (el.tail or ""))
    parent.remove(el)

def cclass(el):
    return (el.get("class") or "")

# ---------------------------------------------------------------- 2a. unrendered links
AC_NS = {"ac": "http://atlassian.com/content",
         "ri": "http://atlassian.com/resource/identifier"}
_XML_ENT_OK = re.compile(r"&(?!(?:amp|lt|gt|quot|apos|#\d+|#x[0-9A-Fa-f]+);)(\w+;)")

def link_miss(ctx, target, text):
    """[link-miss] from the DOM pass: same record post_process writes."""
    rel = (ctx.get("cur_rec") or {}).get("relpath", "")
    ctx.setdefault("missing_links", []).append(
        {"page": rel, "target": target, "text": text})
    print(f"[link-miss] {rel}: {target} ({text or '—'})")

def placeholder_link(img, ctx):
    """Confluence renders a link it failed to transform as
    <img class="transform-error" data-encoded-xml="<ac:link>...">. The XML is
    the storage format of that link. -> (text, href or None) for an ac:link,
    None for any other placeholder (those stay dropped). href is the export's
    own NNN.html(#anchor) -- post_process turns it into a [[wikilink]] like
    every other page link; a target outside the export -> text + [link-miss]."""
    enc = img.get("data-encoded-xml")
    if not enc:
        return None
    xml = urllib.parse.unquote_plus(enc)
    if "<ac:link" not in xml:
        return None
    # storage format carries HTML entities (&nbsp;) the XML parser does not know
    xml = _XML_ENT_OK.sub(lambda m: html.unescape("&" + m.group(1)), xml)
    wrapped = ('<r xmlns:ac="%s" xmlns:ri="%s">%s</r>'
               % (AC_NS["ac"], AC_NS["ri"], xml))
    try:
        root = etree.fromstring(wrapped.encode("utf-8"),
                                etree.XMLParser(recover=True, resolve_entities=False))
    except etree.XMLSyntaxError:
        return None
    link = root.find(".//ac:link", AC_NS) if root is not None else None
    if link is None:
        return None
    body = link.find("ac:link-body", AC_NS)
    text = "".join(body.itertext()) if body is not None else ""
    if not text.strip():
        pt = link.find("ac:plain-text-link-body", AC_NS)
        text = (pt.text or "") if pt is not None else ""
    page = link.find("ri:page", AC_NS)
    att = link.find("ri:attachment", AC_NS)
    ri = "{%s}" % AC_NS["ri"]
    title = (page.get(ri + "content-title") or "") if page is not None else ""
    skey = (page.get(ri + "space-key") or "") if page is not None else ""
    anchor = link.get("{%s}anchor" % AC_NS["ac"]) or ""
    if not text.strip():
        text = (title or (att.get(ri + "filename") if att is not None else "")
                or anchor)
    if not text.strip():
        return None
    frag = "#" + anchor if anchor else ""
    if page is not None and title:
        pid = None
        if not skey or skey.casefold() == SPACE.casefold():
            pid = ctx["title2id"].get(normtitle(title))
        if pid:
            return text, os.path.basename(ctx["pages"][pid]["href"]) + frag
        link_miss(ctx, (f"{skey}:" if skey else "") + title + frag, text.strip())
        return text, None
    if page is None and att is None and anchor:
        return text, frag                          # anchor on this very page
    link_miss(ctx, (att.get(ri + "filename") if att is not None else "")
              or "ac:link", text.strip())
    return text, None

# ---------------------------------------------------------------- 2b. data: images
DATA_EXT = {"image/png": ".png", "image/jpeg": ".jpg", "image/jpg": ".jpg",
            "image/gif": ".gif", "image/svg+xml": ".svg", "image/webp": ".webp",
            "image/bmp": ".bmp"}

def save_data_uri(src, ctx):
    """data:image/...;base64,... -> flat asset name (bytes kept in ctx["blobs"],
    written next to the copied attachments). Name: <pageid>_inline_<sha1[:10]>
    -- stable across runs, the same picture twice on a page is one file.
    -> None for a non-image or undecodable URI (dropped like an icon)."""
    m = re.match(r"data:([^;,]*)((?:;[^;,]*)*),(.*)\Z", src, re.S)
    if not m:
        return None
    ext = DATA_EXT.get(m.group(1).strip().lower())
    if not ext:
        return None
    try:
        if ";base64" in m.group(2).lower():
            data = base64.b64decode(re.sub(r"\s+", "", m.group(3)), validate=False)
        else:
            data = urllib.parse.unquote_to_bytes(m.group(3))
    except (ValueError, TypeError):
        return None
    if not data:
        return None
    pid = (ctx.get("cur_rec") or {}).get("id", "page")
    flat = f"{pid}_inline_{hashlib.sha1(data).hexdigest()[:10]}{ext}"
    ctx.setdefault("blobs", {})[flat] = data
    return flat

# ---------------------------------------------------------------- 2c. colour
# Colour is meaning in this corpus (a red "да" in a mandatory column, a green
# new field). Only NON-default colour is kept: the editor paints nearly every
# span with the theme's text colour, and wrapping those would bury the page.
FG_DEFAULT = {"#172b4d", "#333333", "#000000"}
BG_NEUTRAL = {"#ffffff", "#f4f5f7", "#f1f2f4"}
CSS_NAMED = {
    "black": "#000000", "white": "#ffffff", "red": "#ff0000", "green": "#008000",
    "blue": "#0000ff", "yellow": "#ffff00", "orange": "#ffa500",
    "purple": "#800080", "gray": "#808080", "grey": "#808080",
    "silver": "#c0c0c0", "maroon": "#800000", "olive": "#808000",
    "lime": "#00ff00", "aqua": "#00ffff", "teal": "#008080", "navy": "#000080",
    "fuchsia": "#ff00ff"}
_NOT_A_COLOUR = {"inherit", "initial", "unset", "revert", "currentcolor", "auto"}
_STYLE_FG = re.compile(r"(?:^|;)\s*color\s*:\s*([^;]+)", re.I)
_STYLE_BG = re.compile(r"(?:^|;)\s*background(?:-color)?\s*:\s*([^;]+)", re.I)
_BLOCKISH = HEADINGS | {
    "p", "div", "li", "ul", "ol", "dl", "dt", "dd", "table", "thead", "tbody",
    "tfoot", "tr", "td", "th", "caption", "blockquote", "pre", "hr", "section",
    "article", "header", "footer", "figure", "figcaption", "center", "form",
    "fieldset", "details", "summary", "nav", "aside", "main"}
_CODEISH = {"code", "pre", "tt", "kbd", "samp"}
_NOCOLOUR = ("", "")                # (fg, bg): nothing to paint
_MIXED = object()
CLR_OPEN = "ZZCLRO"                 # ZZCLROF<fg|N>B<bg|N>ZZ ... ZZCLRCZZ
CLR_CLOSE = "ZZCLRCZZ"

def _unvar(v):
    """var(--a, var(--b, #hex)) -> #hex: the fallback of every var(), innermost
    last. A var() without fallback is not a colour we can print."""
    while v.startswith("var("):
        depth, comma, end = 0, -1, -1
        for i, ch in enumerate(v):
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    end = i
                    break
            elif ch == "," and depth == 1 and comma < 0:
                comma = i
        if comma < 0 or end < 0:
            return ""
        v = v[comma + 1:end].strip()
    return v

def css_hex(v):
    """CSS colour value -> '#rrggbb' (lowercase), '' when it is none/unknown."""
    v = re.sub(r"!important", "", v or "", flags=re.I).strip().lower()
    v = _unvar(v)
    m = re.fullmatch(r"#([0-9a-f]{3}|[0-9a-f]{6}|[0-9a-f]{8})", v)
    if m:
        h = m.group(1)
        return "#" + ("".join(c * 2 for c in h) if len(h) == 3 else h[:6])
    m = re.fullmatch(r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*"
                     r"(?:,\s*(\d*\.?\d+)\s*)?\)", v)
    if m:
        if m.group(4) is not None and float(m.group(4)) == 0:
            return ""                                 # fully transparent
        return "#" + "".join(f"{min(int(x), 255):02x}" for x in m.group(1, 2, 3))
    return CSS_NAMED.get(v, "")

def fg_value(raw):
    """Text colour -> None (not declared: inherit), '' (default), '#hex'."""
    r = re.sub(r"\s+", "", (raw or "").lower())
    if not r or r in _NOT_A_COLOUR:
        return None
    if r.startswith("var(--ds-text,"):                # the theme's text colour
        return ""
    h = css_hex(raw)
    return "" if (not h or h in FG_DEFAULT) else h

def bg_value(raw):
    """Background -> None (not declared), '' (neutral), '#hex'."""
    r = re.sub(r"\s+", "", (raw or "").lower())
    if not r or r in _NOT_A_COLOUR:
        return None
    if "--ds-surface" in r or re.search(r"gr[ae]y-subtlest", r):
        return ""
    h = css_hex(raw)
    return "" if (not h or h in BG_NEUTRAL or h == "transparent") else h

def fg_decl(el):
    m = _STYLE_FG.search(el.get("style") or "")
    if m:
        return fg_value(m.group(1))
    if el.tag == "font" and el.get("color"):
        return fg_value(el.get("color"))
    return None

def bg_decl(el):
    if el.tag in ("td", "th"):                        # a cell paints itself: 6d
        return ""
    m = _STYLE_BG.search(el.get("style") or "")
    return bg_value(m.group(1)) if m else None

def cell_bg_of(cell):
    """Cell highlight: data-highlight-colour, else the highlight-X class, else
    a background style. -> '#hex' or '' (neutral / none)."""
    v = cell.get("data-highlight-colour")
    if not v:
        m = re.search(r"(?:^|\s)highlight-(\S+)", cell.get("class") or "")
        v = m.group(1) if m else None
    if not v:
        m = _STYLE_BG.search(cell.get("style") or "")
        v = m.group(1) if m else None
    return bg_value(v) or ""

def _eff(el, eff):
    fg, bg = fg_decl(el), bg_decl(el)
    return (eff[0] if fg is None else fg, eff[1] if bg is None else bg)

def _has_text(t):
    return bool(t) and bool(re.sub(r"[\s​﻿]+", "", t))

def _has_block(el):
    return any(isinstance(d.tag, str) and d.tag in _BLOCKISH
               for d in el.iterdescendants())

def _uniform(el, eff, code_neutral=False):
    """The (fg, bg) shared by ALL text of el's subtree; None when it has no
    text, _MIXED otherwise. Code has the colour its text has in the source
    (it is never painted itself, but plain code must not ride inside a
    coloured run and take the colour on); code_neutral=True counts it as no
    text at all -- how a link is judged, see _colour_container."""
    if code_neutral and el.tag in _CODEISH:
        return None
    e, seen = _eff(el, eff), set()
    if _has_text(el.text):
        seen.add(e)
    for c in el:
        if isinstance(c.tag, str):
            u = _uniform(c, e, code_neutral)
            if u is _MIXED:
                return _MIXED
            if u is not None:
                seen.add(u)
        if _has_text(c.tail):
            seen.add(e)
        if len(seen) > 1:
            return _MIXED
    return next(iter(seen)) if seen else None

def _edge_ok(el):
    """An element whose edges may be trimmed: not code (verbatim), not a link
    (its text is the link label), not a picture."""
    return isinstance(el.tag, str) and el.tag not in _CODEISH | {"a", "img", "br"}

def _strip_leading(el):
    """Detach whitespace and <br> that open el's content (at any depth) ->
    [str | <br>] in document order. A colour span must start at text: a
    leading line break inside it splits the span over two lines."""
    out = []
    while True:
        t = el.text or ""
        if t.strip():
            s = t.lstrip()
            if len(s) < len(t):
                out.append(t[:len(t) - len(s)])
                el.text = s
            return out
        if t:
            out.append(t)
            el.text = None
        if not len(el):
            return out
        first = el[0]
        if isinstance(first.tag, str) and first.tag == "br":
            tail, first.tail = first.tail, None
            el.remove(first)
            el.text = tail
            out.append(first)
            continue
        if _edge_ok(first):
            out += _strip_leading(first)
        return out

def _strip_trailing(el):
    """Mirror of _strip_leading for the end of el. A trailing line break left
    inside put "</span>" alone on the next line -- an HTML block start for
    CommonMark, which swallows the lines after it."""
    out = []
    while True:
        if not len(el):
            t = el.text or ""
            s = t.rstrip()
            if len(s) < len(t):
                out.insert(0, t[len(s):])
                el.text = s
            return out
        last = el[-1]
        t = last.tail or ""
        if t.strip():
            s = t.rstrip()
            if len(s) < len(t):
                out.insert(0, t[len(s):])
                last.tail = s
            return out
        if t:
            out.insert(0, t)
            last.tail = None
        if isinstance(last.tag, str) and last.tag == "br":
            el.remove(last)
            out.insert(0, last)
            continue
        if _edge_ok(last):
            out = _strip_trailing(last) + out
        return out

def _style_token(pair):
    fg, bg = pair
    return f"{CLR_OPEN}F{fg[1:] if fg else 'N'}B{bg[1:] if bg else 'N'}ZZ"

def _coloured_texts(el, eff):
    """[(colour, text)] of the non-default coloured text in el's subtree,
    consecutive text of one colour merged -- what a [colour-lost] entry names."""
    out = []
    def add(col, t):
        if not _has_text(t) or col == _NOCOLOUR:
            if out and t:
                out.append(None)                    # breaks a merge
            return
        if out and out[-1] is not None and out[-1][0] == col:
            out[-1] = (col, out[-1][1] + t)
        else:
            out.append((col, t))
    def walk(n, e):
        e = _eff(n, e)
        add(e, n.text or "")
        for c in n:
            if isinstance(c.tag, str) and c.tag in _CODEISH:
                if out:
                    out.append(None)   # code is never painted: not "lost"
            elif isinstance(c.tag, str):
                walk(c, e)
            add(e, c.tail or "")
    walk(el, eff)
    return [(c, re.sub(r"\s+", " ", t).strip()) for c, t in
            (x for x in out if x is not None)]

def _split_link(a, e):
    """A link whose label is only partly coloured -> one link per colour
    stretch of its label, all to the same target, in place of a. Each piece
    is then of one colour and is painted whole like any link. Split only at
    the link's own top level: its text, each child, each tail. Whitespace-
    only text, <br>, <img> and code are neutral and ride with the stretch
    they sit in. Whitespace at a split point goes between the pieces, not
    into a label. False (a untouched) when a child is itself of mixed colour
    or holds a block -- such a link stays unpainted and is logged."""
    ea = _eff(a, e)
    toks = []                               # [(colour | None, str | element)]
    if a.text:
        toks.append((ea if _has_text(a.text) else None, a.text))
    for c in a:
        if not isinstance(c.tag, str) or c.tag in ("br", "img") \
                or c.tag in _CODEISH:
            col = None
        elif c.tag in _BLOCKISH or _has_block(c):
            return False
        else:
            col = _uniform(c, ea, code_neutral=True)
            if col is _MIXED:
                return False
        toks.append((col, c))
        if c.tail:
            toks.append((ea if _has_text(c.tail) else None, c.tail))
    segs = []                               # [[colour, [str | element]]]
    for col, x in toks:
        if segs and (col is None or segs[-1][0] in (None, col)):
            if segs[-1][0] is None:
                segs[-1][0] = col
            segs[-1][1].append(x)
        else:
            segs.append([col, [x]])
    if len(segs) < 2:
        return False
    parent, tail = a.getparent(), a.tail
    pieces = []
    for k, (_, xs) in enumerate(segs):
        n = etree.Element("a")
        for key, val in a.attrib.items():
            if k == 0 or key not in ("id", "name"):
                n.set(key, val)
        for x in xs:
            if isinstance(x, str):
                if len(n):
                    n[-1].tail = (n[-1].tail or "") + x
                else:
                    n.text = (n.text or "") + x
            else:
                x.tail = None
                n.append(x)
        pieces.append(n)
    out = []                                # the new siblings, in order
    for k, n in enumerate(pieces):
        lead = _strip_leading(n) if k > 0 else []
        trail = _strip_trailing(n) if k < len(pieces) - 1 else []
        out += lead + [n] + trail
    prev = None
    for x in out:
        if isinstance(x, str):
            if prev is None:
                if a.getprevious() is not None:
                    p_ = a.getprevious()
                    p_.tail = (p_.tail or "") + x
                else:
                    parent.text = (parent.text or "") + x
            else:
                prev.tail = (prev.tail or "") + x
        else:
            x.tail = None
            a.addprevious(x)
            prev = x
    prev.tail = (prev.tail or "") + (tail or "")
    parent.remove(a)
    return True

def _colour_container(el, e, lost=None):
    """Paint the inline runs of el. e: (fg, bg) in force for el's own text.
    Items are el.text, each child, each tail. A run is a stretch of items of
    one colour; neutral items (whitespace, <br>, <img>) ride inside a run but
    never start or end it. Code rides inside a run only when its text has the
    run's colour in the source, otherwise it ends the run; it never starts or
    ends one (code is never painted itself). Blocks (headings too: painted
    inside), <pre> and inline elements of mixed colour break runs -- the
    latter are painted inside, recursively. A link is painted whole: a link
    whose label is partly coloured is first split into one link per colour
    stretch (_split_link); one that cannot be split loses its colour, and
    lost (a list) gets (colour, text) for each coloured piece of it."""
    for c in list(el):
        if isinstance(c.tag, str) and c.tag == "a" \
                and _uniform(c, e, code_neutral=True) is _MIXED:
            _split_link(c, e)
    kids = list(el)
    items = []                      # (kind, colour) per position; kind c|n|b|k
    def text_item(t):
        return ("c", e) if _has_text(t) else ("n", None)
    items.append(text_item(el.text))
    for c in kids:
        if not isinstance(c.tag, str) or c.tag in ("br", "img"):
            items.append(("n", None))
        elif c.tag in (_CODEISH - {"pre"}):
            u = _uniform(c, e)
            items.append(("n", None) if u is None else
                         ("b", None) if u is _MIXED else ("k", u))
        elif c.tag == "pre":
            items.append(("b", None))              # never painted inside
        elif c.tag in _BLOCKISH or _has_block(c):
            items.append(("b", None))
            _colour_container(c, _eff(c, e), lost)
        else:
            u = _uniform(c, e)
            un = _uniform(c, e, code_neutral=True)
            if un is None:                         # nothing but code inside:
                items.append(("n", None) if u is None else     # it is code
                             ("b", None) if u is _MIXED else ("k", u))
            elif u is _MIXED and c.tag == "a":
                # a link is painted whole. Plain code inside a coloured
                # link does not split it (the link label is one piece); a
                # mix _split_link could not take apart leaves the link
                # unpainted -- logged
                if un is _MIXED:
                    un = _NOCOLOUR
                    if lost is not None:
                        lost.extend(_coloured_texts(c, e))
                items.append(("c", un))
            elif u is _MIXED:
                items.append(("b", None))
                _colour_container(c, _eff(c, e), lost)
            elif u is None:
                items.append(("n", None))
            else:
                items.append(("c", u))
        items.append(text_item(c.tail))
    runs, cur = [], None            # cur: [colour, first, last] (item indices)
    for i, (kind, col) in enumerate(items):
        if kind == "c" and cur is not None and col == cur[0]:
            cur[2] = i
            continue
        if kind == "n" or (kind == "k" and cur is not None and col == cur[0]):
            continue
        if cur is not None:
            runs.append(cur)
            cur = None
        if kind == "c" and col != _NOCOLOUR:
            cur = [col, i, i]
    if cur is not None:
        runs.append(cur)
    if not runs:
        return
    # explode: every text item becomes a <zzt> element, so a run is a plain
    # slice of children (strip_tags("zzt") glues the text back afterwards)
    nodes = []
    t0, el.text = el.text, None
    if t0:
        z = E("zzt", t0); el.insert(0, z); nodes.append(z)
    else:
        nodes.append(None)
    for c in kids:
        nodes.append(c)
        t, c.tail = c.tail, None
        if t:
            z = E("zzt", t); c.addnext(z); nodes.append(z)
        else:
            nodes.append(None)
    for col, i, j in runs:
        seg = [n for n in nodes[i:j + 1] if n is not None]
        first, last = seg[0], seg[-1]
        if first.tag == "zzt":                     # edge whitespace stays outside
            t = first.text
            lead = t[:len(t) - len(t.lstrip())]
            # a task-list marker belongs to the list item, not to the colour
            if i == 0 and el.tag == "li":
                mk = re.match(r"\[[ xX]\] \s*", t[len(lead):])
                if mk:
                    lead += mk.group(0)
            if lead:
                first.text = t[len(lead):]
                first.addprevious(E("zzt", lead))
        if last.tag == "zzt":
            t = last.text
            trail = t[len(t.rstrip()):]
            if trail:
                last.text = t[:len(t) - len(trail)]
                last.addnext(E("zzt", trail))
        # ...and whitespace / <br> at the edges INSIDE a painted element too
        lead = _strip_leading(first) if first.tag != "zzt" and _edge_ok(first) else []
        trail = _strip_trailing(last) if last.tag != "zzt" and _edge_ok(last) else []
        w = etree.Element("span")
        w.set("data-zzclr", _style_token(col))
        first.addprevious(w)
        for n in seg:
            w.append(n)
        for x in lead:
            w.addprevious(E("zzt", x) if isinstance(x, str) else x)
        anchor = w
        for x in trail:
            node = E("zzt", x) if isinstance(x, str) else x
            anchor.addnext(node)
            anchor = node

def colour_runs(content, ctx=None):
    """Paint non-default colour as plain-text tokens around inline runs; they
    ride through pandoc and tablemd untouched and restore_colours() turns them
    into <span style="...">. Tokens, not <span style>, because pandoc rewrites
    an attributed span in its own way, and tablemd drops spans altogether.
    Colour that cannot be kept (part of a link's label) -> [colour-lost]."""
    lost = []
    _colour_container(content, _NOCOLOUR, lost)
    rel = ((ctx or {}).get("cur_rec") or {}).get("relpath", "")
    for (fg, bg), text in lost:
        if not text:
            continue
        colour = ";".join(x for x in (f"color:{fg}" if fg else "",
                                      f"background-color:{bg}" if bg else "") if x)
        if ctx is not None:
            ctx.setdefault("colour_lost", []).append(
                {"page": rel, "text": text, "colour": colour})
        print(f"[colour-lost] {rel}: «{text}» ({colour})")
    etree.strip_tags(content, "zzt")
    for w in content.xpath(".//span[@data-zzclr]"):
        tok = w.get("data-zzclr")
        del w.attrib["data-zzclr"]
        w.text = tok + (w.text or "")
        if len(w):
            w[-1].tail = (w[-1].tail or "") + CLR_CLOSE
        else:
            w.text += CLR_CLOSE

_CLR_TOKEN = re.compile(r"ZZCLROF([0-9a-f]{6}|N)B([0-9a-f]{6}|N)ZZ")

def restore_colours(md):
    """Colour tokens -> inline HTML. A run that lost all its text on the way
    (pandoc dropped a lone nbsp) is unwrapped: never a span around nothing."""
    def style(m):
        parts = []
        if m.group(1) != "N":
            parts.append(f"color:#{m.group(1)}")
        if m.group(2) != "N":
            parts.append(f"background-color:#{m.group(2)}")
        return ";".join(parts)
    md = re.sub(_CLR_TOKEN.pattern + r"(\s*)" + re.escape(CLR_CLOSE), r"\3", md)
    md = _CLR_TOKEN.sub(lambda m: f'<span style="{style(m)}">', md)
    return md.replace(CLR_CLOSE, "</span>")

def clean_dom(content, ctx):
    """ctx: dict to collect asset/attachment copy tasks. content: <div id=main-content>"""
    # 0. remove style + script + toc macro
    for el in content.xpath(".//style | .//script"):
        el.getparent().remove(el)
    for el in content.xpath(".//div[contains(@class,'toc-macro')]"):
        el.getparent().remove(el)
    # also remove the wrapper div(s) Confluence adds around toc
    # 1. code blocks: pre.syntaxhighlighter-pre
    for pre in content.xpath(".//pre[contains(@class,'syntaxhighlighter-pre')]"):
        params = pre.get("data-syntaxhighlighter-params", "") or ""
        mb = re.search(r"brush:\s*([^;]+)", params)
        brush = (mb.group(1).strip().lower() if mb else "")
        lang = BRUSH.get(brush, brush if re.match(r"^[a-z0-9+#]+$", brush) else "")
        code_txt = pre.text_content()
        new_pre = etree.Element("pre")
        code = etree.SubElement(new_pre, "code")
        if lang:
            code.set("class", "language-" + lang)
        code.text = code_txt
        # also drop the surrounding codeHeader (panel title) -> keep as preceding bold
        replace_with(pre, new_pre)
    # 1b. code panel header (title) -> keep text as a strong line before code panel
    for hd in content.xpath(".//div[contains(@class,'codeHeader')]"):
        txt = hd.text_content().strip()
        if txt:
            p = E("p"); b = etree.SubElement(p, "strong"); b.text = txt
            replace_with(hd, p)
        else:
            hd.getparent().remove(hd)
    # 2. expand macro -> bold label + unwrapped content
    for cont in content.xpath(".//div[contains(@class,'expand-container')]"):
        label_el = cont.xpath(".//*[contains(@class,'expand-control-text')]")
        label = (label_el[0].text_content().strip() if label_el else "Подробнее")
        # default UI placeholder of a title-less expand is not content
        if re.fullmatch(r"(Нажмите здесь для раскрытия|Click here to expand)\s*(\.{3}|…)?", label):
            label = "Подробнее"
        body = cont.xpath(".//div[contains(@class,'expand-content')]")
        new = etree.Element("div")
        p = etree.SubElement(new, "p")
        s = etree.SubElement(p, "strong"); s.text = "▸ " + label
        if body:
            for c in list(body[0]):
                new.append(c)
            if body[0].text and body[0].text.strip():
                # wrap stray text
                tp = etree.SubElement(new, "p"); tp.text = body[0].text
        replace_with(cont, new)
        unwrap(new)
    # 3. info/note/warning/tip macros -> blockquote with label
    for mac in content.xpath(".//*[contains(@class,'confluence-information-macro')]"):
        cl = cclass(mac)
        kind = "information"
        for k in INFO_STYLE:
            if "confluence-information-macro-" + k in cl:
                kind = k; break
        emoji, label = INFO_STYLE[kind]
        # panel title (<p class="title">) lives OUTSIDE the body div in the
        # export -- taking only the body silently dropped it
        _tsel = "*[contains(concat(' ', normalize-space(@class), ' '), ' title ')]"
        ttl = mac.xpath(f"./{_tsel} | "
                        f"./*[contains(@class,'confluence-information-macro-body')]/{_tsel}")
        ttl_txt = ttl[0].text_content().strip() if ttl else ""
        if ttl:
            ttl[0].getparent().remove(ttl[0])      # never twice
        bodyl = mac.xpath(".//*[contains(@class,'confluence-information-macro-body')]")
        bq = etree.Element("blockquote")
        p0 = etree.SubElement(bq, "p")
        st = etree.SubElement(p0, "strong"); st.text = f"{emoji} {label}"
        if ttl_txt:
            pt = etree.SubElement(bq, "p")
            sb = etree.SubElement(pt, "strong"); sb.text = ttl_txt
        if bodyl:
            body = bodyl[0]
            if body.text and body.text.strip():
                tp = etree.SubElement(bq, "p"); tp.text = body.text
            for c in list(body):
                bq.append(c)
        replace_with(mac, bq)
    # 4. status lozenges -> strong with emoji
    for sp in content.xpath(".//span[contains(@class,'status-macro')]"):
        cl = cclass(sp); kind = ""
        m = re.search(r"aui-lozenge-(\w+)", cl)
        if m: kind = m.group(1)
        emoji = LOZENGE_EMOJI.get(kind, "⚪")
        txt = sp.text_content().strip()
        b = E("strong", f"{emoji} {txt}")
        replace_with(sp, b)
    # 5. user mentions -> @Name
    for a in content.xpath(".//a[contains(@class,'user-mention')]"):
        name = a.text_content().strip()
        b = E("strong", "@" + name)
        replace_with(a, b)
    # 5b. inline task lists -> GFM checkboxes ([x]/[ ])
    for li in content.xpath(".//ul[contains(@class,'inline-task-list')]/li"):
        marker = "[x] " if "checked" in (li.get("class") or "") else "[ ] "
        li.text = marker + (li.text or "")
    # 5c. drop empty emphasis wrappers (Confluence <strong><br/></strong> -> stray **\**)
    for el in content.xpath(".//strong | .//em | .//b | .//i"):
        if not "".join(el.itertext()).strip():
            unwrap(el)
    # 5d. normalize emphasis boundaries -- pandoc emits broken GFM for
    #     <strong>X<br/></strong> ("**X\**") and <strong>X </strong>и<strong>Y
    #     ("**X **и**Y**", invalid close). Trailing <br> and edge whitespace
    #     move OUT of the emphasis; same-kind nested emphasis is flattened
    #     (pandoc would print "****X****").
    EM_KIND = {"strong": "strong", "b": "strong", "em": "em", "i": "em"}
    WS = " \t\r\n\xa0"
    for el in list(content.iter()):
        if not isinstance(el.tag, str) or el.tag not in EM_KIND:
            continue
        anc, nested = el.getparent(), False
        while anc is not None:
            if isinstance(anc.tag, str) and EM_KIND.get(anc.tag) == EM_KIND[el.tag]:
                nested = True; break
            anc = anc.getparent()
        if nested:
            unwrap(el); continue
        parent = el.getparent()
        if parent is None:
            continue
        while len(el) and el[-1].tag == "br":
            br = el[-1]
            el.remove(br)
            br.tail = (br.tail or "") + (el.tail or "")
            el.tail = None
            parent.insert(list(parent).index(el) + 1, br)
        t = el.text or ""
        lead = t[:len(t) - len(t.lstrip(WS))]
        if lead:
            el.text = t[len(lead):]
            i = list(parent).index(el)
            if i == 0:
                parent.text = (parent.text or "") + lead
            else:
                parent[i - 1].tail = (parent[i - 1].tail or "") + lead
        if len(el):
            t2 = el[-1].tail or ""
            trail = t2[len(t2.rstrip(WS)):]
            if trail:
                el[-1].tail = t2[:len(t2) - len(trail)]
                el.tail = trail + (el.tail or "")
        else:
            t2 = el.text or ""
            trail = t2[len(t2.rstrip(WS)):]
            if trail and t2.strip(WS):
                el.text = t2[:len(t2) - len(trail)]
                el.tail = trail + (el.tail or "")
    # 5e. Confluence anchor macro: <span class="confluence-anchor-link" id="X">
    #     is the TARGET of every #X link. Its class dies in 6c and the span
    #     itself in 7 -- so materialize the target as <a name="X"></a> next to
    #     it (the form fix_tables keeps and md renderers understand). The span
    #     stays for its content, if it ever has any.
    for sp in content.xpath(".//span[contains(@class,'confluence-anchor-link')][@id]"):
        aid = (sp.get("id") or "").strip()
        del sp.attrib["id"]
        if not aid:
            continue
        a = etree.Element("a")
        a.set("name", aid)
        sp.addprevious(a)
    # 6. images
    for img in content.xpath(".//img"):
        src = img.get("src", "") or ""
        alt = img.get("alt") or img.get("data-linked-resource-default-alias") or ""
        # drop decorative confluence icons and generic file/code placeholders,
        # incl. jira-macro avatars (external <img> that pins pages to the tracker)
        if ("images/icons/" in src or src.startswith("images/icons")
                or src.startswith("plugins/servlet")
                or "placeholder-" in os.path.basename(src)
                or "viewavatar" in src or "useravatar" in src
                or "/images/emoticons/" in src):
            # a LINK the export could not render: its words are content
            ph = placeholder_link(img, ctx)
            if ph is not None:
                text, href = ph
                if href:
                    a = E("a", text); a.set("href", href)
                    replace_with(img, a)
                else:
                    drop_to_text(img, text)
                continue
            if "unknown-macro" in src:      # macro the export could not render:
                p = E("p")                  # dropping it silently loses content
                s = etree.SubElement(p, "strong")
                s.text = "⚠️ неизвестный макрос Confluence — содержимое не выгружено, см. страницу-источник"
                replace_with(img, p); continue
            img.getparent().remove(img); continue
        new_src = None
        if src.startswith("data:"):
            # the picture IS the URI: a data: link is dead for link-check and
            # bloats the page -- it becomes an asset file like any attachment
            flat = save_data_uri(src, ctx)
            if not flat:                   # dropped like an icon; its tail
                drop_to_text(img, ""); continue        # (the words after) stays
            new_src = "ASSET::" + flat
        elif src.startswith("attachments/"):
            new_src = register_image(src, ctx)
        elif src.startswith("download/"):
            new_src = register_download(src, ctx)
        elif src.startswith("rest/") and "thumbnail" in src:
            # broken thumbnail -> resolve to underlying attachment
            resolved = resolve_thumbnail(src, ctx)
            if resolved:
                new_src = resolved
            else:
                img.getparent().remove(img); continue
        elif src.startswith("https://mermaid.ink/"):
            code = decode_mermaid(src)
            if code:
                pre = etree.Element("pre")
                c = etree.SubElement(pre, "code"); c.set("class", "language-mermaid")
                c.text = code
                replace_with(img, pre); continue
            else:
                new_src = src  # keep external
        elif src.startswith("http"):
            new_src = src
        else:
            new_src = src
        if new_src:
            # strip Confluence's data-* / class noise AND width/height: a sized
            # <img> survives pandoc as raw HTML, so the picture never becomes
            # ![[embed]] and link-check cannot see it (88 of 230 in a real
            # corpus). Rendered size is lost on purpose.
            for a in list(img.attrib):
                del img.attrib[a]
            img.set("src", new_src)
            if alt:
                img.set("alt", alt)
    # 6a. drop colgroup: tablemd ignores it, and fallback raw HTML is cleaner
    #     without it. colspan/rowspan are NOT normalized away anymore -- such
    #     tables (0 in this corpus) fall back to raw HTML via tablemd.Fallback.
    for cg in content.xpath(".//colgroup"):
        cg.getparent().remove(cg)
    # 6b. empty attachment anchors (file-card macro): put the filename inside,
    #     BEFORE pandoc -- applies both inside tables and in flow text.
    tablemd.fill_empty_anchors(content)
    # 6b'. markdown typed by hand in the editor: "[label](" + <a> + ")". The
    #      author meant ONE link called label; left alone it became
    #      "\[label\]([[page]])" -- a link whose target is a wikilink.
    #      Only this exact shape: "[label](" right before the link AND ")"
    #      right after it. Bracket text in any other shape (no ")" after the
    #      link, say) is left as written. The same shape on the markdown
    #      side (a ")" the md link rule leaves after a link) -> post_process.
    for a in content.xpath(".//a[@href]"):
        if not (a.tail or "").startswith(")"):
            continue
        prev, parent = a.getprevious(), a.getparent()
        before = (prev.tail if prev is not None else parent.text) or ""
        m = re.search(r"\[([^\[\]\n]+)\]\($", before)
        if not m or not m.group(1).strip():
            continue
        if prev is not None:
            prev.tail = before[:m.start()]
        else:
            parent.text = before[:m.start()]
        a.tail = a.tail[1:]
        # parens of the URL are percent-encoded (the same URL): unencoded,
        # the md link rules cut it at the first ")" and the rest of it stayed
        # on the page as a stray ")"
        a.set("href", a.get("href").replace("(", "%28").replace(")", "%29"))
        for c in list(a):
            a.remove(c)
        a.text = m.group(1)
    # 6b''. colour: non-default text colour / highlight -> colour runs, and a
    #       coloured table cell keeps its background (set after the scrub).
    #       Styles are read here, before 6c throws them away.
    colour_runs(content, ctx)
    cell_bgs = [(c, cell_bg_of(c)) for c in content.xpath(".//td | .//th")]
    # 6c. attribute scrub (whitelist per tag). Confluence hangs class/style/
    #     rel/data-* on everything; pandoc keeps ANY attributed inline element
    #     as raw HTML, so flow links stayed <a class=...> instead of becoming
    #     [text](url) -> [[wikilinks]]. Fallback tables also serialize cleaner.
    #     Must run AFTER all class-driven macro handling and 6b (fill_empty_
    #     anchors reads data-linked-resource-default-alias/aria-label).
    for el in content.iter():
        if not isinstance(el.tag, str):
            continue
        keep = KEEP_ATTRS.get(el.tag, ())
        for k in list(el.attrib):
            if k not in keep:
                del el.attrib[k]
    # 6d. the one style that survives: a coloured cell's background. tablemd
    #     turns it into a span around the cell content, a raw-HTML fallback
    #     table keeps it on the td/th as is
    for c, bg in cell_bgs:
        if bg:
            c.set("style", f"background-color:{bg}")
    # 7. drop all remaining Confluence wrapper tags (table-wrap, code panel,
    #    wiki-content, citation/font spans...) keeping their text & children.
    etree.strip_tags(content, "div", "span", "font")
    return content

def inner_html(el):
    parts = []
    if el.text and el.text.strip():
        parts.append(html.escape(el.text))
    for c in el:
        parts.append(lxml.html.tostring(c, encoding="unicode"))
    return "".join(parts)

# ---------------------------------------------------------------- asset registration
IMG_EXT = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".bmp")

def flat_name(src):
    parts = src.split("/")
    if src.startswith("attachments/") and len(parts) >= 3:
        return parts[1] + "_" + "_".join(parts[2:])
    return os.path.basename(src)

def register(src, ctx):
    """Record a file to copy. Images -> assets/, everything else -> attachments/.
    One source -> one folder -> one flat basename (so [[basename]] is unambiguous)."""
    flat = flat_name(src)
    folder = "assets" if flat.lower().endswith(IMG_EXT) else "attachments"
    ctx["files"][src] = (folder, flat)
    return flat

def register_image(src, ctx):
    return "ASSET::" + register(src, ctx)

def register_download(src, ctx):
    return "ASSET::" + register(src, ctx)

def resolve_thumbnail(src, ctx):
    # rest/.../thumbnail/<attId>/<ver>  -> find attachments/*/<attId>.<ext>
    m = re.search(r"thumbnail/(\d+)/", src)
    if not m: return None
    hit = ctx["att_index"].get(m.group(1))
    if hit and hit.lower().endswith(IMG_EXT):
        return "ASSET::" + register(hit, ctx)
    return None

def decode_mermaid(src):
    try:
        m = re.search(r"pako:([A-Za-z0-9_\-]+)", src)
        if not m: return None
        data = m.group(1)
        pad = "=" * (-len(data) % 4)
        raw = base64.urlsafe_b64decode(data + pad)
        txt = zlib.decompress(raw).decode("utf-8")
        obj = json.loads(txt)
        return obj.get("code")
    except Exception:
        return None

# ---------------------------------------------------------------- pandoc
def pandoc_html(fragment_html):
    # gfm keeps raw_html ON by default: simple tables -> pipe tables, complex
    # tables (block content in cells) -> preserved as <table> HTML (no data loss).
    p = subprocess.run(
        ["pandoc", "-f", "html", "-t", "gfm", "--wrap=none"],
        input=fragment_html.encode("utf-8"),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if p.returncode != 0:
        raise RuntimeError(f"pandoc failed (rc={p.returncode}): "
                           f"{p.stderr.decode('utf-8', 'replace').strip()}")
    return p.stdout.decode("utf-8")

# ---------------------------------------------------------------- anchor targets
# Obsidian/Foam jump to a `#fragment` by heading text or by a block id (`^id`)
# and know nothing about <a name>. So an anchor is classified by WHERE it sits,
# and that decides the shape of every link pointing at it.
def anchor_kind(a, content):
    """-> (kind, heading element or None). kind: 'cell' (table cell -- nothing
    resolves there), 'heading' (link by heading text), 'block' (link by an
    appended ^block-id)."""
    h, in_cell, node = None, False, a
    while node is not None and node is not content:
        tag = node.tag
        if isinstance(tag, str):
            if tag in ("td", "th"):
                in_cell = True
            elif tag in HEADINGS and h is None:
                h = node
        node = node.getparent()
    return ("cell" if in_cell else ("heading" if h is not None else "block")), h

def block_id(name):
    """Block id for an anchor: ASCII, short, stable across runs and machines
    (NFC first -- macOS hands out NFD). Obsidian accepts only letters, digits
    and dashes after the ^."""
    h = hashlib.sha1(unicodedata.normalize("NFC", name).encode("utf-8"))
    return "a-" + h.hexdigest()[:8]

def strip_md_inline(s):
    """Heading line -> its plain text: what a reader sees and what a
    [[page#Heading]] fragment is matched against. Only PAIRED markers are
    dropped, so a lone `_` inside a word survives."""
    s = re.sub(r"!\[\[[^\]\n]*\]\]", "", s)                       # embeds
    s = re.sub(r"\[\[[^\]|\n]*\|([^\]\n]*)\]\]", r"\1", s)        # [[t|alias]]
    s = re.sub(r"\[\[([^\]\n]*)\]\]", r"\1", s)
    s = re.sub(r"\[((?:[^\[\]\\]|\\.)*?)\]\([^)\s]*(?:\s+\"[^\"]*\")?\)", r"\1", s)
    s = re.sub(r"<[^>]+>", "", s)                                 # raw inline html
    s = _CLR_TOKEN.sub("", s).replace(CLR_CLOSE, "")              # colour (2c)
    for pat in (r"\*\*(.+?)\*\*", r"__(.+?)__", r"~~(.+?)~~",
                r"\*(.+?)\*", r"`+([^`]+)`+"):
        s = re.sub(pat, r"\1", s)
    return unesc(s)

def head_frag(s):
    """Heading text as a wikilink fragment. Obsidian strips #, |, [, ], ^ from a
    heading before matching -- do exactly that, so what we write resolves."""
    return re.sub(r"\s+", " ", re.sub(r"[\[\]|#^\\]", "", s)).strip()

def _fence_lines(lines):
    """Indices of lines inside fenced code -- a block id must never be appended
    there (the fence is verbatim)."""
    inside, fence, out = False, None, set()
    for i, l in enumerate(lines):
        m = re.match(r"^[ \t]*(`{3,}|~{3,})", l)
        if not inside and m:
            inside, fence = True, m.group(1)[0] * 3
            out.add(i)
        elif inside:
            out.add(i)
            if re.match(r"^[ \t]*" + fence + r"+[ \t]*$", l):
                inside, fence = False, None
    return out

def _block_last_line(lines, i):
    """Last line of the paragraph starting at line i. pandoc --wrap=none puts a
    paragraph on one line; only a <br/> continues it (trailing backslash), and a
    trailing lone backslash line is dropped later, so it cannot carry the id."""
    j, n = i, len(lines)
    while j + 1 < n and lines[j].rstrip().endswith("\\") and lines[j + 1].strip():
        j += 1
    while j > i and lines[j].strip() == "\\":
        j -= 1
    return j

def _put_block_id(lines, j, bid):
    """Append ` ^bid` to the line, or reuse the id already standing there: a
    block has ONE id, and two anchors in one paragraph must not fight over it."""
    line = lines[j].rstrip()
    m = re.search(r"\^([A-Za-z0-9][A-Za-z0-9\-]*)$", line)
    if m and (len(line) == len(m.group(0)) or line[-len(m.group(0)) - 1].isspace()):
        return m.group(1)
    lines[j] = (line + " " if line else "") + "^" + bid
    return bid

def anchor_targets(md, anchors):
    """For every masked anchor decide what a link to it must say after the `#`
    and, for a paragraph anchor, put the block id into the markdown.
    anchors: [(name, kind)] -> (md, [fragment per anchor])."""
    lines = md.split("\n")
    fenced = _fence_lines(lines)
    at = {}
    for i, line in enumerate(lines):
        for m in re.finditer(r"ZZANCHOR(\d+)ZZ", line):
            at.setdefault(int(m.group(1)), i)
    out = []
    for i, (name, kind) in enumerate(anchors):
        li, frag = at.get(i), ""
        if li is not None and kind == "heading":
            for j in range(li + 1, min(li + 4, len(lines))):
                s = lines[j].strip()
                if not s:
                    continue
                m = re.match(r"^#{1,6}[ \t]+(.*)$", s)
                if m:
                    frag = head_frag(strip_md_inline(m.group(1)))
                break
        elif li is not None and kind == "block" and li not in fenced:
            j = _block_last_line(lines, li)
            if not (re.match(r"^[ \t]*\|.*\|[ \t]*$", lines[j])
                    or re.match(r"^[ \t]*(#{1,6}[ \t]|```|~~~)", lines[j])):
                frag = "^" + _put_block_id(lines, j, block_id(name))
        out.append(frag or wl_frag(name))     # cell, or nothing recognizable
    return "\n".join(lines), out

def convert_body(content, page="", fallbacks=None, anchors_out=None):
    """HTML element -> markdown. Text goes through pandoc; every top-level
    <table> is converted by tablemd (our GFM writer). Raw-HTML fallback only
    for tablemd.Fallback reasons (colspan/rowspan, nested table, long <pre>),
    always logged (and collected into `fallbacks` for .ingest.json).
    Placeholders are re-inserted keeping the line indentation, so tables
    inside list items stay attached to their items.
    Anchor targets are masked the same way: neither pandoc (which turns
    <a name="x"></a> into <span id="x"></span>) nor the table writer (which
    renders a text-less <a> as nothing) keeps them, so they travel as plain
    text tokens through BOTH and come back as raw inline HTML.
    anchors_out (a dict) collects this page's anchor map -- anchor name (folded)
    -> the fragment a wikilink must carry to reach it; post_process writes both
    same-page and cross-page links against those maps."""
    anchors = []
    for a in content.xpath(".//a[@name or @id]"):
        aname = re.sub(r"\s+", " ", a.get("name") or a.get("id") or "").strip()
        if not aname:
            continue
        token = f"ZZANCHOR{len(anchors)}ZZ"
        kind, h = anchor_kind(a, content)
        anchors.append((aname, kind))
        # a link that is ALSO an anchor target keeps being a link; the target
        # is emitted next to it as a separate empty anchor
        keep_link = bool(a.get("href") or len(a) or "".join(a.itertext()).strip())
        if keep_link:
            a.attrib.pop("name", None)
            a.attrib.pop("id", None)
        # Confluence hangs most anchors on a heading. Left inside, the anchor
        # glues raw HTML to the heading text -- and that text is what a
        # [[page#Heading]] link resolves against -- so it is hoisted to its
        # own line right before the heading instead.
        if h is not None:
            h.addprevious(E("p", token))
            if not keep_link:
                drop_to_text(a, "")
        elif keep_link:
            insert_text_before(a, token)
        else:
            drop_to_text(a, token)
    saved = []
    for i, t in enumerate(content.xpath(".//table[not(ancestor::table)]")):
        ph = etree.Element("p")
        ph.text = f"ZZTBLPLACEHOLDER{i}ZZ"
        t.addprevious(ph)
        # the table's tail is text AFTER </table> -- it belongs to the page,
        # not to the table; removing the element used to eat it
        if t.tail:
            ph.tail = (ph.tail or "") + t.tail
            t.tail = None
        t.getparent().remove(t)
        saved.append(t)
    md = pandoc_html(inner_html(content))
    for i, t in enumerate(saved):
        try:
            tmd = tablemd.table_to_gfm(t, unroll_pre=UNROLL_PRE,
                                       expand_spans=EXPAND_SPANS)
        except tablemd.Fallback as fb:
            print(f"[table-fallback] {page}: {fb.reason}")
            if fallbacks is not None:
                fallbacks.append({"page": page, "reason": fb.reason})
            tmd = lxml.html.tostring(t, encoding="unicode").strip()
            # a newline inside a raw HTML block ends it for md renderers --
            # the tail would render as text. Collapse to one line (except
            # <pre>: its newlines are content).
            if "\n" in tmd and "<pre" not in tmd:
                tmd = re.sub(r"\s*\n\s*", " ", tmd)
        pat = re.compile(rf"(?m)^([ \t]*)ZZTBLPLACEHOLDER{i}ZZ[ \t]*$")
        if pat.search(md):
            md = pat.sub(lambda m: "\n".join(m.group(1) + l for l in tmd.split("\n")), md, count=1)
        else:                                    # placeholder ended up inline
            md = _inline_table(md, f"ZZTBLPLACEHOLDER{i}ZZ", tmd)
    # where each anchor landed decides how a link can reach it -- and a
    # paragraph anchor gets its block id written into the markdown here
    md, frags = anchor_targets(md, anchors)
    if anchors_out is not None:
        for (aname, _kind), frag in zip(anchors, frags):
            anchors_out.setdefault(anchor_key(wl_frag(aname)), frag)
    for i, (aname, _kind) in enumerate(anchors):
        md = md.replace(f"ZZANCHOR{i}ZZ",
                        f'<a name="{html.escape(aname, quote=True)}"></a>')
    return restore_colours(md)

def _inline_table(md, ph, tmd):
    """Placeholder that pandoc kept inline (a table as the only/first child of
    a <li> gives a tight item "- ZZ..ZZ"). Glueing a pipe table to the list
    marker produces broken GFM -- the header row must start its own line,
    indented to the item's content column."""
    lines = md.split("\n")
    for i, line in enumerate(lines):
        if ph not in line:
            continue
        pre, _, post = line.partition(ph)
        m = re.match(r"^([ \t]*(?:[-*+]|\d+[.)])[ \t]+)(.*)$", pre)
        if m and "\n" in tmd:
            marker, lead = m.group(1), m.group(2)
            ind = " " * len(marker.expandtabs(4))   # item's content column
            body, tail = tmd.split("\n"), post.strip()
            if lead.strip():                        # text, blank line, table
                out = [marker + lead.rstrip(), ""]
                out += [ind + l if l else l for l in body]
            else:                                   # table starts at the marker
                out = [marker + body[0]]
                out += [ind + l if l else l for l in body[1:]]
            if tail:
                out += ["", ind + tail]
            lines[i] = "\n".join(out)
        else:
            lines[i] = pre + tmd + post
        break
    return "\n".join(lines)

# ---------------------------------------------------------------- 3. post-process md
LINKTEXT = r"((?:[^\[\]\\\n]|\\.)*?)"   # link text: single line, tolerant of escaped [], non-greedy
def unesc(s):
    return re.sub(r"\\([!-/:-@\[-`{-~])", r"\1", s)

decode_tiny = tablemd.decode_tiny   # Confluence /x/<code> -> candidate pageId(s)

def wl_frag(s):
    """The `#anchor` part of a wikilink: without the characters that would
    close the link early. A fragment taken from a URL goes through
    urllib.parse.unquote first -- pandoc percent-encodes everything non-ASCII."""
    return re.sub(r"[\[\]|#\\]", "", s).strip()

def anchor_key(name):
    """Anchors are matched the way Obsidian and link_check resolve names:
    NFC + case-insensitive (macOS hands out NFD)."""
    return unicodedata.normalize("NFC", name).casefold()

def page_frag(pid, frag, ctx):
    """The `#fragment` of a link to page `pid`, in the form that navigates: the
    target page's anchor map (built while its body was converted) turns an
    anchor name into heading text or a ^block-id.
    -> "" when that page has no such anchor: a fragment leading nowhere is not
    written out (link-check would rightly call it broken, and the reader lands
    on top of the page either way) -- the caller logs it as [link-miss] and
    keeps the page link. A page missing from `anchors` was not converted in
    this run (ONLY/LIMIT): its fragment is left exactly as written."""
    if not frag:
        return ""
    amap = (ctx.get("anchors") or {}).get(pid)
    if amap is None:
        return frag
    return amap.get(anchor_key(frag), "")

# relative Confluence paths: /pages/viewpage.action?..., /display/KEY/Title,
# /spaces/KEY/pages/N/..., /x/<tiny>, /download/attachments/N/file
REL_CONF = re.compile(r"/(?:pages|display|spaces|x|download)/")

def normtitle(t):
    return re.sub(r"\s+", " ", html.unescape(t)).strip().lower()

def resolve_confluence(url, ctx):
    """Confluence URL -> ('page', pid) | ('file', local_href) | ('keep',)."""
    pages, title2id, namemap = ctx["pages"], ctx["title2id"], ctx.get("namemap", {})
    u = html.unescape(url)
    m = re.search(r"[?&]pageId=(\d+)", u)
    if m and m.group(1) in pages:
        return ("page", m.group(1))
    m = re.search(r"/display/[^/]+/([^?#]+)", u)
    if m:
        pid = title2id.get(normtitle(urllib.parse.unquote(m.group(1).replace("+", " "))))
        if pid:
            return ("page", pid)
    m = re.search(r"/spaces/[^/]+/pages/(\d+)(?:[/?#]|$)", u)   # modern URL form
    if m and m.group(1) in pages:
        return ("page", m.group(1))
    m = re.search(r"/x/([A-Za-z0-9_\-]+)", u)
    if m:
        for pid in decode_tiny(m.group(1)):
            if pid in pages:
                return ("page", pid)
    m = re.search(r"/download/attachments/(\d+)/([^?#]+)", u)
    if m:
        name = urllib.parse.unquote(m.group(2)).strip()
        local = namemap.get(name) or namemap.get(name.lower())
        if local:
            return ("file", local)
    return ("keep",)

def mask_fences(md):
    """Pull fenced code blocks out of the markdown before the link/cleanup
    rules run: a fence is verbatim content, and rewriting links, dropping
    "&#10;" or eating a lone backslash inside an example corrupts it.
    -> (masked md, blocks); restore with unmask_fences."""
    out, blocks, cur, fence = [], [], None, None
    for line in md.split("\n"):
        if fence is None:
            m = re.match(r"^[ \t]*(`{3,}|~{3,})", line)
            if m:
                fence, cur = m.group(1)[0] * 3, [line]
            else:
                out.append(line)
        else:
            cur.append(line)
            if re.match(r"^[ \t]*" + fence + r"+[ \t]*$", line):
                out.append(f"ZZFENCEBLOCK{len(blocks)}ZZ")
                blocks.append("\n".join(cur))
                fence, cur = None, None
    if cur:                                        # unterminated fence
        out.append(f"ZZFENCEBLOCK{len(blocks)}ZZ")
        blocks.append("\n".join(cur))
    return "\n".join(out), blocks

def unmask_fences(md, blocks):
    for i, b in enumerate(blocks):
        md = md.replace(f"ZZFENCEBLOCK{i}ZZ", b)
    return md

def post_process(md, rec, pages, href2id, ctx):
    # code fences are verbatim: hide them from every rule below
    md, fences = mask_fences(md)
    # image embeds: ![alt](ASSET::flat)  -> ![[flat]]   (Obsidian/Foam embed by basename)
    # pandoc percent-encodes URLs -> unquote, else non-ASCII embed names break
    def img_sub(m):
        flat = urllib.parse.unquote(m.group(2))
        return f"![[{flat}]]"
    md = re.sub(r"!\[([^\]]*)\]\(ASSET::([^)\s]+)\)", img_sub, md)
    # plain links that became ASSET (img wrapped in link) -> embed
    md = re.sub(r"\[([^\]]*)\]\(ASSET::([^)\s]+)\)",
                lambda m: f"![[{urllib.parse.unquote(m.group(2))}]]", md)
    # picture used as the link text of a page link: [![[x]]](1234.html) is not
    # markdown at all (the embed keeps its own brackets) -> embed + page link
    def img_link_sub(m):
        embed, fn = m.group(1), m.group(2)
        pid = href2id.get(fn) or id_of(fn)
        if pid and pid in pages:
            return f"{embed} [[{pages[pid]['basename']}|{pages[pid]['title']}]]"
        return embed
    md = re.sub(r"\[(!\[\[[^\]\n]+\]\])\]\((?:\./)?([0-9A-Za-z_\-]+\.html)(?:#[^)]*)?\)",
                img_link_sub, md)
    # a link that leads nowhere is recorded, never dropped in silence -- that
    # is how a corpus quietly loses its cross-references
    def miss(target, text):
        ctx.setdefault("missing_links", []).append(
            {"page": rec["relpath"], "target": target, "text": text})
        print(f"[link-miss] {rec['relpath']}: {target} ({text or '—'})")
    # internal page links: [text](1234.html#anchor) -> [[basename|text]]
    def link_sub(m):
        text = unesc(m.group(1).strip())
        # pandoc keeps <strong> inside a clean <a> as [**X**](u): the link IS
        # the emphasis, and a wikilink alias renders "**" literally -> unwrap
        text = re.sub(r"^\*\*(.+)\*\*$", r"\1", text)
        target = m.group(2)
        anchor = m.group(3) or ""
        fn = os.path.basename(target)
        # #anchor of the target page: rewritten to the form that navigates
        # (heading text / ^block-id) once we know which page it points at
        frag = (wl_frag(urllib.parse.unquote(anchor[1:]))
                if anchor.startswith("#") else "")
        if fn == "index.html":
            tb = "Home" + (f"#{frag}" if frag else "")
            return f"[[{tb}|{text}]]" if text and text != "Home" else f"[[{tb}]]"
        pid = href2id.get(fn) or id_of(fn)
        if pid and pid in pages:
            got = page_frag(pid, frag, ctx)
            if frag and not got:
                miss(f"{pages[pid]['basename']}#{frag}", text)
            tb = pages[pid]["basename"] + (f"#{got}" if got else "")
            ttl = pages[pid]["title"]
            if not text or text == ttl:
                return f"[[{tb}]]"
            # link text that is just the page's own confluence URL (pasted
            # smart-link): the URL says nothing a reader needs -- drop it
            if re.match(r"https?://", text) and resolve_confluence(text, ctx) == ("page", pid):
                return f"[[{tb}]]"
            return f"[[{tb}|{text}]]"
        # target outside this export (page moved to another space, partial
        # export, deleted page): the link degrades to plain text -- record it,
        # silence here is how a corpus quietly loses its cross-references
        miss(fn, text)
        return text or fn
    md = re.sub(r"\[" + LINKTEXT + r"\]\((?:\./)?([0-9A-Za-z_\-]+\.html)(#[^)]*)?\)", link_sub, md)
    # links to an anchor of THIS page: [text](#id-...) -> [[#anchor|text]], the
    # Obsidian/Foam form of a link inside the current note (link_check sees an
    # empty target and rightly leaves it alone). The anchor is decoded and
    # spelled as the <a name> convert_body kept; a fragment that matches no
    # anchor of the page (a Confluence typo, a truncated name) is a dead link
    # -- it degrades to text and is logged like a link out of the export
    page_anchors = ctx.get("page_anchors") or {}
    def frag_sub(m):
        text = unesc(m.group(1).strip())
        text = re.sub(r"^\*\*(.+)\*\*$", r"\1", text)   # см. link_sub
        frag = wl_frag(urllib.parse.unquote(m.group(2)))
        name = page_anchors.get(anchor_key(frag))
        if name:
            return f"[[#{name}|{text}]]" if text else f"[[#{name}]]"
        miss("#" + frag, text)
        return text or f"#{frag}"
    # the fragment may hold balanced parens (#id-Платежи(Paynet)-info): a plain
    # [^)]+ would cut the link in half
    md = re.sub(r"(?<!!)\[" + LINKTEXT + r"\]\(#((?:[^()\s]|\([^()\s]*\))+)\)",
                frag_sub, md)
    # attachment file links: [text](attachments/<pid>/<file>) -> [[flat|text]]
    def att_sub(m):
        text = unesc(m.group(1).strip())
        src = m.group(2)
        if not os.path.exists(os.path.join(SRC, src)):
            return text or os.path.basename(src)          # missing file -> plain text
        flat = register(src, ctx)
        if flat.lower().endswith(IMG_EXT):
            return f"![[{flat}]]"
        return f"[[{flat}|{text or flat}]]"
    md = re.sub(r"\[" + LINKTEXT + r"\]\((?:\./)?(attachments/\d+/[^)\s]+)\)", att_sub, md)
    # download links
    md = re.sub(r"\[" + LINKTEXT + r"\]\((?:\./)?(download/[^)\s]+)\)",
                lambda m: f"[[{register(m.group(2), ctx)}|{unesc(m.group(1).strip()) or 'файл'}]]", md)
    # confluence cross-links in flow: [text](https://confluence.../...) -> wikilink/file
    def md_conf(m):
        text, url = unesc(m.group(1).strip()), m.group(2)
        text = re.sub(r"^\*\*(.+)\*\*$", r"\1", text)   # см. link_sub
        kind = resolve_confluence(url, ctx)
        if kind[0] == "page":
            b, t = pages[kind[1]]["basename"], pages[kind[1]]["title"]
            # the #anchor of an absolute link means the same as in the relative
            # form; dropped, it landed the reader on top of a long page
            want = wl_frag(urllib.parse.unquote(
                html.unescape(url).partition("#")[2]))
            frag = page_frag(kind[1], want, ctx)
            if want and not frag:
                miss(f"{b}#{want}", text)
            if frag:
                b += "#" + frag
            if (not text or normtitle(text) == normtitle(t)
                    or (re.match(r"https?://", text)
                        and resolve_confluence(text, ctx) == kind)):
                return f"[[{b}]]"
            return f"[[{b}|{text}]]"
        if kind[0] == "file":
            flat = register(kind[1], ctx)
            return f"![[{flat}]]" if flat.lower().endswith(IMG_EXT) else f"[[{flat}|{text or flat}]]"
        # a RELATIVE Confluence link to something outside the export is a
        # path on the Confluence server: with --base-url it gets its host back,
        # without it there is nothing to point at -> text + [link-miss]
        if REL_CONF.match(url) and "createpage.action" not in url:
            if not BASE_URL:
                miss(url, text)
                return text or url
            full = BASE_URL + url
            label = full if text == url else m.group(1)
            return f"[{label}]({full})"
        return m.group(0)
    md = re.sub(r"(?<!!)\[" + LINKTEXT + r"\]\(((?:https?:|/)[^)\s]+)\)", md_conf, md)
    # autolinks <url>: pandoc emits them for <a href="X">X</a> (text == href);
    # resolve confluence targets like md_conf does. Fence-aware: a literal
    # <http://...> inside example code must stay untouched. Same loop also
    # unescapes pandoc's over-escaped arrows ("A -\> B" -- the source had a
    # plain "->"); inline `code` spans are skipped.
    def auto_conf(m):
        kind = resolve_confluence(m.group(1), ctx)
        if kind[0] == "page":
            b = pages[kind[1]]["basename"]
            want = wl_frag(urllib.parse.unquote(m.group(1).partition("#")[2]))
            frag = page_frag(kind[1], want, ctx)
            if want and not frag:
                miss(f"{b}#{want}", "")
            return f"[[{b}{'#' + frag if frag else ''}]]"
        if kind[0] == "file":
            flat = register(kind[1], ctx)
            return f"![[{flat}]]" if flat.lower().endswith(IMG_EXT) else f"[[{flat}|{flat}]]"
        return m.group(0)
    def outside_code(line, fn):
        out, pos = [], 0
        for m in re.finditer(r"`+[^`]*`+", line):
            out.append(fn(line[pos:m.start()])); out.append(m.group(0)); pos = m.end()
        out.append(fn(line[pos:]))
        return "".join(out)
    # markdown typed by hand in the editor, as it stands after the rules above:
    # "\[label\](" + link + ")" -> ONE link called label (see 6b' in
    # clean_dom). 6b' sees only a ")" that follows the <a> in the source; a
    # link to a page whose title ends in ")" -- "...+(списание)" -- is cut by
    # the md link rule at the title's "(", and the link's own ")" is left
    # right after it: the same shape, caught here. Only this exact shape.
    def typed_sub(m):
        label = m.group(1)
        if not label.strip():
            return m.group(0)
        if m.group(2):
            return f"[[{m.group(2)}|{unesc(label.strip())}]]"
        return f"[{label.strip()}]({m.group(3) or m.group(4)})"
    typed_rx = (r"\\\[([^\[\]\n]+)\\\]\((?:\[\[([^\]|\\\n]+)(?:\\?\|[^\]\n]*)?\]\]"
                r"|\[[^\[\]\n]*\]\((https?://[^)\s]+)\)|<(https?://[^>\s]+)>)\)")
    fix_inline = lambda s: re.sub(typed_rx, typed_sub,
                                  re.sub(r"<(https?://[^>\s]+)>", auto_conf, s)
                                  ).replace("-\\>", "->")
    lines, in_fence = md.split("\n"), False
    for i, l in enumerate(lines):
        if re.match(r"^[ \t]*(```|~~~)", l):
            in_fence = not in_fence
        elif not in_fence:
            lines[i] = outside_code(l, fix_inline)
    md = "\n".join(lines)
    # --- raw HTML left inside complex tables: rewrite refs to relative paths ---
    # (Obsidian/Foam don't parse [[..]]/![[..]] inside raw <table> blocks, but DO
    #  render <img src> and <a href> with note-relative paths.)
    here = os.path.dirname(rec["relpath"])
    def relq(target_relpath):
        rel = os.path.relpath(target_relpath, here) if here else target_relpath
        return urllib.parse.quote(rel)
    # images inside HTML: src="ASSET::flat" -> note-relative assets path
    md = re.sub(r'src="ASSET::([^"]+)"',
                lambda m: f'src="{relq("assets/" + m.group(1))}"', md)
    # internal page links inside HTML: <a href="1234.html#x"> -> relative .md
    def html_page_link(m):
        fn, anchor = m.group(1), (m.group(2) or "")
        pid = href2id.get(fn + ".html") or id_of(fn + ".html")
        if pid and pid in pages:
            return f'<a href="{relq(pages[pid]["relpath"])}"'
        if fn == "index":
            return f'<a href="{relq("Home.md")}"'
        return m.group(0)
    md = re.sub(r'<a href="([0-9A-Za-z_\-]+)\.html(#[^"]*)?"', html_page_link, md)
    # attachment links inside HTML: <a href="attachments/.."> -> relative + register
    def html_att_link(m):
        src = m.group(1)
        if not os.path.exists(os.path.join(SRC, src)):
            return m.group(0)
        flat = register(src, ctx)
        folder = "assets" if flat.lower().endswith(IMG_EXT) else "attachments"
        return f'<a href="{relq(folder + "/" + flat)}"'
    md = re.sub(r'<a href="(attachments/\d+/[^"]+)"', html_att_link, md)
    # confluence cross-links inside raw HTML: <a href="https://confluence.../..">
    def html_conf(m):
        pre, url = m.group(1), m.group(2)
        kind = resolve_confluence(url, ctx)
        if kind[0] == "page":
            return f'{pre}href="{relq(pages[kind[1]]["relpath"])}"'
        if kind[0] == "file":
            flat = register(kind[1], ctx)
            folder = "assets" if flat.lower().endswith(IMG_EXT) else "attachments"
            return f'{pre}href="{relq(folder + "/" + flat)}"'
        if (REL_CONF.match(html.unescape(url))              # см. md_conf
                and "createpage.action" not in url):
            if BASE_URL:
                return f'{pre}href="{BASE_URL}{url}"'
            miss(html.unescape(url), "")
            return f'{pre}href="ZZRELMISS"'     # -> plain text, below
        return m.group(0)
    md = re.sub(r'(<a\s[^>]*?)href="((?:https?:|/)[^"]+)"', html_conf, md)
    # "create page" redlinks point to nothing -> collapse to plain text
    md = re.sub(r'<a\b[^>]*href="[^"]*createpage\.action[^"]*"[^>]*>(.*?)</a>', r"\1", md, flags=re.S)
    # ...and so does a relative link out of the export without --base-url
    md = re.sub(r'<a\b[^>]*href="ZZRELMISS"[^>]*>(.*?)</a>', r"\1", md, flags=re.S)
    md = re.sub(r"\[" + LINKTEXT + r"\]\([^)]*createpage\.action[^)]*\)", lambda m: unesc(m.group(1)), md)
    # strip pandoc newline-entity artifact inside raw HTML tables
    md = md.replace("&#10;", "")
    # drop empty-text external links (e.g. mermaid.live "edit" links left after
    # diagram decode). NOT image syntax: ![](url) is an alt-less picture, and
    # eating its "[](url)" left a lone "!" where a picture used to be
    md = re.sub(r"(?<!!)\[\]\(https?://[^)\s]+\)", "", md)
    # drop standalone backslash lines (pandoc artifact from trailing <br/>)
    md = re.sub(r"(?m)^[ \t]*\\[ \t]*$", "", md)
    # un-escape GFM task checkboxes pandoc escaped: "- \[x\]" -> "- [x]"
    md = re.sub(r"(?m)^(\s*(?:>\s*)*[-*]\s+)\\\[([ xX])\\\]", r"\1[\2]", md)
    # remove leftover empty-bold artifact from <strong><br/></strong> (keep "****" masked data!)
    md = re.sub(r"\*\*\\\*\*", "", md)
    # escape "|" inside [[wikilinks]] on pipe-table rows -- an unescaped pipe
    # (from [[base|text]] produced by the link rules above) would split the cell
    md = "\n".join(
        re.sub(r"\[\[([^\]|]*)(?<!\\)\|([^\]]*)\]\]", r"[[\1\\|\2]]", line)
        if re.match(r"^[ \t]*\|.*\|[ \t]*$", line) else line
        for line in md.split("\n"))
    # collapse 3+ blank lines
    md = re.sub(r"\n{3,}", "\n\n", md)
    return unmask_fences(md, fences).strip()

# ---------------------------------------------------------------- frontmatter + footer
def yaml_escape(s):
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'

def extract_attachments(doc, ctx):
    """Parse the page-level 'Attachments:' greybox (outside main-content).
    Returns (manifest list, namemap: human filename -> local 'attachments/..' href)."""
    out, seen, namemap = [], set(), {}
    for sec in doc.xpath("//div[contains(@class,'pageSection')]"):
        if not sec.xpath(".//h2[@id='attachments']"):
            continue
        for a in sec.xpath(".//a[@href]"):
            href = a.get("href") or ""
            if not href.startswith("attachments/"):
                continue
            if not os.path.exists(os.path.join(SRC, href)):
                continue                                   # not in export -> skip (no broken link)
            name = a.text_content().strip()
            if name:
                namemap[name] = href
                namemap[name.lower()] = href
            flat = register(href, ctx)
            if flat in seen:
                continue
            seen.add(flat)
            out.append((flat, name or flat))
    return out, namemap

def breadcrumb_chain(rec, pages):
    chain = []
    cur = rec["parent"]
    while cur and cur in pages:
        chain.append(pages[cur])
        cur = pages[cur]["parent"]
    return list(reversed(chain))

def build_document(rec, body_md, pages, attachments=None):
    chain = breadcrumb_chain(rec, pages)
    fm = ["---"]
    fm.append(f"title: {yaml_escape(rec['title'])}")
    fm.append(f"confluence_id: {rec['id']}")
    if rec["parent"] and rec["parent"] in pages:
        fm.append(f"parent: \"[[{pages[rec['parent']]['basename']}]]\"")
    if VIEW:
        fm.append(f"source: {VIEW.format(id=rec['id'])}")
    fm.append(f"space: {SPACE}")
    fm.append("---")
    out = ["\n".join(fm), ""]
    # breadcrumb
    if chain:
        crumb = " › ".join(f"[[{c['basename']}|{c['title']}]]" for c in chain)
        out.append(crumb)
        out.append("")
    # title
    out.append(f"# {rec['title']}")
    out.append("")
    out.append(body_md)
    # attachments manifest
    if attachments:
        out.append("")
        out.append("## Вложения")
        out.append("")
        for flat, name in attachments:
            out.append(f"- [[{flat}|{name}]]")
    # footer: source + relations (footnotes/links)
    foot = ["", "---", ""]
    rels = []
    if rec["parent"] and rec["parent"] in pages:
        rels.append(f"**Родитель:** [[{pages[rec['parent']]['basename']}|{pages[rec['parent']]['title']}]]")
    kids = rec.get("children", [])
    if kids:
        kid_links = ", ".join(f"[[{pages[k]['basename']}|{pages[k]['title']}]]" for k in kids if k in pages)
        rels.append(f"**Дочерние страницы:** {kid_links}")
    if VIEW:
        rels.append(f"**Источник:** [Confluence {SPACE} / {rec['id']}]({VIEW.format(id=rec['id'])})")
    if rels:                                     # parentless leaf + no base-url -> no footer
        foot.append("  \n".join(rels))
        out.append("\n".join(foot))
    return "\n".join(out) + "\n"

def page_content_key(rec, body_md, attachments):
    """What "изменено" is measured on: the page's own content. Deliberately
    without frontmatter (source:/space:), breadcrumbs and footer -- those
    shift when --base-url changes or a neighbour is renamed, and a report
    that marks 300 pages changed for that is worse than no report."""
    parts = [rec["title"], body_md]
    if attachments:
        parts += [f"{flat}|{name}" for flat, name in attachments]
    return "\n".join(parts)

# ---------------------------------------------------------------- change report
def _nfc_fold(s):
    return unicodedata.normalize("NFC", s).casefold()

def spec_impact(spec_dir, affected):
    """Scan sibling spec/ for [[wikilinks]] hitting changed/removed basenames.
    affected: {folded basename -> rendered list item}. -> [(doc_rel, [items])]"""
    hits = []
    for dirpath, _, files in os.walk(spec_dir):
        for f in sorted(files):
            if not f.endswith(".md"):
                continue
            p = os.path.join(dirpath, f)
            text = open(p, encoding="utf-8", errors="replace").read()
            # wikilink target up to |/#; strip the \ of table-escaped \| aliases
            targets = {t.rstrip("\\").strip()
                       for t in re.findall(r"\[\[([^\]|#]+)", text)}
            items = sorted({affected[_nfc_fold(t)]
                            for t in targets if _nfc_fold(t) in affected})
            if items:
                hits.append((os.path.relpath(p, spec_dir), items))
    hits.sort(key=lambda h: h[0])          # os.walk order is not an order
    return hits

def render_changes(snapshot, pages, prev, added, changed, moved, removed,
                   spec_hits, warns=()):
    """Human report for a re-ingest. Live pages -> wikilinks; removed pages ->
    plain names (a wikilink would be broken)."""
    def wl(pid):
        return f"[[{pages[pid]['basename']}|{pages[pid]['title']}]]"
    L = ["---", f'title: "Изменения снапшота Confluence {snapshot}"', "---", "",
         f"# Изменения снапшота Confluence {snapshot}", ""]
    for w in warns:
        L += ["> ⚠️ " + w, ""]
    if added:
        L += ["## Добавлено", ""] + [f"- {wl(p)}" for p in added] + [""]
    if changed:
        L += ["## Изменено", ""] + [f"- {wl(p)}" for p in changed] + [""]
    if moved:
        L += ["## Перемещено", ""] + [
            f"- {wl(p)} — `{prev[p]['relpath']}` → `{pages[p]['relpath']}`"
            for p in moved] + [""]
    if removed:
        L += ["## Удалено", ""] + [
            f"- {prev[p]['title']} (`{prev[p]['relpath']}`)" for p in removed] + [""]
    if spec_hits:
        L += ["## Возможно устарели в spec/", "",
              "Документы ссылаются на изменённые/удалённые страницы:", ""]
        L += [f"- `spec/{doc}` → " + ", ".join(items) for doc, items in spec_hits] + [""]
    return "\n".join(L).rstrip("\n") + "\n"

# ---------------------------------------------------------------- main
def main():
    pages, href2id, root_id = build_map(SRC)
    print(f"[map] {len(pages)} pages, root={root_id} ({pages[root_id]['title']})")
    if os.environ.get("MAP_ONLY"):
        for pid, r in list(pages.items())[:15]:
            print(f"  {r['relpath']}")
        return
    # previous run's pagemap (if any) -- baseline for the change report
    try:
        prev = json.load(open(os.path.join(OUT, ".pagemap.json"), encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        prev = {}
    # ...and the previous run's own parameters: same export + different flags
    # is not a content change, but the hashes differ all the same
    try:
        prev_meta = json.load(open(os.path.join(OUT, ".space.json"), encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        prev_meta = {}
    # pages of OTHER spaces sharing this wiki are not part of this diff (and
    # their entries survive in the map below -- ingesting a second space must
    # not erase the first one's history)
    prev_other = {p: r for p, r in prev.items()
                  if r.get("space") and r["space"] != SPACE}
    if prev_other:
        prev = {p: r for p, r in prev.items() if p not in prev_other}
        print(f"[map] {len(prev_other)} страниц другого спейса в .pagemap.json — "
              "в дифф не входят")
    prev_flags = prev_meta.get("flags")
    flags_warn = ""
    if prev and (prev_flags != RUN_FLAGS or prev_meta.get("hash_algo") != HASH_ALGO):
        flags_warn = ("флаги отличаются от прошлого прогона, «изменено» может быть "
                      f"ложным: было {flags_str(prev_flags)}, стало {flags_str(RUN_FLAGS)}")
        if prev_meta.get("hash_algo") != HASH_ALGO:
            flags_warn += ("; сменился и формат хэша (версия конвертера "
                           f"{prev_meta.get('converter_version') or 'неизвестна'} → "
                           f"{CONVERTER_VERSION}) — сравнивать содержимое не с чем")
        print("[warn] " + flags_warn, file=sys.stderr)
    version_warn = ""
    if (prev and not flags_warn
            and prev_meta.get("converter_version") != CONVERTER_VERSION):
        # same flags, same hash format, another converter: pages it renders
        # differently (2.5: colour, recovered links) show up as "changed"
        version_warn = ("версия конвертера сменилась "
                      f"({prev_meta.get('converter_version') or 'неизвестна'} → "
                      f"{CONVERTER_VERSION}): «изменено» включает страницы, которые "
                      "новая версия выводит иначе, хотя в Confluence они не менялись")
        print("[warn] " + version_warn, file=sys.stderr)
    # build attachment index (attId -> path) for thumbnail resolution
    att_index = {}
    for dirpath, _, files in os.walk(os.path.join(SRC, "attachments")):
        for f in files:
            rel = os.path.relpath(os.path.join(dirpath, f), SRC)
            att_id = os.path.splitext(f)[0]
            att_index[att_id] = rel
    title2id = {}
    for pid, r in pages.items():
        title2id.setdefault(normtitle(r["title"]), pid)
    ctx = dict(files={}, att_index=att_index, pages=pages, title2id=title2id,
               namemap={}, missing_links=[], anchors={})

    os.makedirs(OUT, exist_ok=True)
    os.makedirs(ASSETS, exist_ok=True)
    os.makedirs(ATTACH, exist_ok=True)

    targets = list(pages.items())
    if ONLY:
        targets = [(pid, r) for pid, r in targets if pid in ONLY]
    if LIMIT:
        targets = targets[:LIMIT]

    # Pass 1: bodies + per-page anchor maps. Links are rewritten only in pass 2:
    # [[B#anchor]] written on page A needs to know where that anchor sits on
    # page B (heading / paragraph / cell), and B may be converted after A.
    n_ok = 0
    fallbacks = []
    converted = []
    for pid, rec in targets:
        fpath = os.path.join(SRC, os.path.basename(rec["href"]))
        if not os.path.exists(fpath):
            print(f"[miss] {rec['href']}"); continue
        doc = lxml.html.parse(fpath).getroot()
        cont = doc.xpath("//div[@id='main-content']")
        if not cont:
            print(f"[nobody] {rec['href']}"); continue
        ctx["cur_rec"] = rec             # link-miss / inline-asset names in clean_dom
        content = clean_dom(cont[0], ctx)
        anchors = {}                 # anchor name -> fragment that navigates
        body_md = convert_body(content, page=rec["relpath"], fallbacks=fallbacks,
                               anchors_out=anchors)
        atts, namemap = extract_attachments(doc, ctx)
        ctx["anchors"][pid] = anchors
        converted.append((pid, rec, body_md, atts, namemap))
    # Pass 2: links, wikilinks and anchors -> the page on disk
    for pid, rec, body_md, atts, namemap in converted:
        ctx["namemap"] = namemap
        ctx["page_anchors"] = ctx["anchors"][pid]
        body_md = post_process(body_md, rec, pages, href2id, ctx)
        document = build_document(rec, body_md, pages, atts)
        outp = os.path.join(OUT, rec["relpath"])
        os.makedirs(os.path.dirname(outp), exist_ok=True)
        open(outp, "w", encoding="utf-8").write(document)
        rec["hash"] = hashlib.sha1(
            page_content_key(rec, body_md, atts).encode("utf-8")).hexdigest()
        n_ok += 1
    print(f"[convert] {n_ok} pages written")
    if ctx["missing_links"]:
        print(f"[link-miss] {len(ctx['missing_links'])} ссылок в никуда "
              "(страница вне выгрузки, якорь без цели) стали текстом "
              "(список — в .ingest.json)")
    if ctx.get("colour_lost"):
        print(f"[colour-lost] {len(ctx['colour_lost'])} цветных фрагментов в "
              "подписях ссылок остались без цвета (список — в .ingest.json)")
    # partial runs (ONLY/LIMIT): unconverted pages keep the previous hash
    for pid, r in pages.items():
        if "hash" not in r:
            r["hash"] = prev.get(pid, {}).get("hash", "")

    # copy files (images -> assets/, others -> attachments/)
    n_a = n_at = miss = 0
    for src, (folder, flat) in ctx["files"].items():
        sp = os.path.join(SRC, src)
        dst = os.path.join(OUT, folder, flat)
        if os.path.exists(sp):
            shutil.copy2(sp, dst)
            if folder == "assets": n_a += 1
            else: n_at += 1
        else:
            miss += 1
    for flat, data in sorted(ctx.get("blobs", {}).items()):   # decoded data: images
        with open(os.path.join(ASSETS, flat), "wb") as fh:
            fh.write(data)
        n_a += 1
    print(f"[files] {n_a} images/diagrams -> assets/, {n_at} -> attachments/ ({miss} missing src)")
    # remove pages that disappeared from the export (re-ingest into same dir).
    # HARD RULE: files without a confluence_id frontmatter (hand-written layers
    # like _TRAINING/, _specs/, _KNOWLEDGE-MAP.md) are NEVER touched.
    # ...and ONLY pages of THIS space: a second space or a partial export
    # ingested into the same wiki would otherwise wipe everything else.
    valid = {os.path.normpath(r["relpath"]) for r in pages.values()}
    candidates, foreign = [], 0
    for dirpath, dirs, files in os.walk(OUT):
        dirs.sort()
        for f in sorted(files):
            if not f.endswith(".md"):
                continue
            p = os.path.join(dirpath, f)
            rel = os.path.normpath(os.path.relpath(p, OUT))
            if rel in valid:
                continue
            head = open(p, encoding="utf-8", errors="replace").read(2048)
            fmm = re.match(r"(?s)\A---\n(.*?)\n---\n", head)
            if not fmm or not re.search(r"(?m)^confluence_id:\s*\d+\s*$", fmm.group(1)):
                continue                          # hand-written -> keep
            sm = re.search(r"(?m)^space:\s*(\S+)\s*$", fmm.group(1))
            if not sm or sm.group(1).strip('"\'') != SPACE:
                foreign += 1                      # another space -> not ours
                continue
            candidates.append((p, rel))
    if foreign:
        print(f"[stale] {foreign} страниц другого спейса не тронуто "
              f"(space: != {SPACE})")
    mass = bool(len(candidates) > MASS_ABS or (
        prev and len(candidates) >= MASS_MIN
        and len(candidates) > MASS_FRAC * len(prev)))
    n_stale, stale_removed, stale_blocked = 0, [], []
    if mass and not ALLOW_MASS_REMOVAL:
        stale_blocked = [rel for _p, rel in candidates]
        print(f"[stale-blocked] к удалению {len(candidates)} страниц из "
              f"{len(prev) or '?'} прошлого прогона — это похоже на неполную "
              "выгрузку, а не на подрезанный спейс. Ничего не удалено.",
              file=sys.stderr)
        for rel in stale_blocked:
            print(f"[stale-blocked] {rel}", file=sys.stderr)
        print("[stale-blocked] проверь выгрузку; если страницы действительно "
              "удалены в Confluence — прогони с --allow-mass-removal",
              file=sys.stderr)
    else:
        for p, rel in candidates:
            os.remove(p)
            n_stale += 1
            stale_removed.append(rel)
            print(f"[stale-removed] {rel}")
        if mass:
            print("[stale] массовое удаление разрешено флагом --allow-mass-removal")
    if n_stale:
        print(f"[stale] {n_stale} vanished pages removed")
    name, snapshot, snapshot_src = parse_space_meta(SRC)
    # ---- change report vs previous .pagemap.json (order of appearance);
    #      first ingest has no baseline -> empty diff, no _CHANGES file
    by_order = lambda pid: pages[pid]["order"]
    added = removed = changed = moved = []
    if prev:
        added   = sorted([p for p in pages if p not in prev], key=by_order)
        removed = sorted([p for p in prev if p not in pages],
                         key=lambda p: prev[p].get("order", 0))
        # moved (rename/reparent changes relpath) excludes the page from
        # "changed": its content differs by construction (title/breadcrumb)
        moved   = sorted([p for p in pages if p in prev
                          and prev[p].get("relpath") != pages[p]["relpath"]], key=by_order)
        changed = sorted([p for p in pages if p in prev
                          and prev[p].get("relpath") == pages[p]["relpath"]
                          and pages[p].get("hash") and prev[p].get("hash")
                          and pages[p]["hash"] != prev[p]["hash"]], key=by_order)
    warns = []
    if flags_warn:
        warns.append(flags_warn)
    if version_warn:
        warns.append(version_warn)
    if stale_blocked:
        warns.append(f"массовое удаление заблокировано: {len(stale_blocked)} страниц "
                     "из «Удалено» остались на диске; проверь полноту выгрузки, "
                     "затем прогони с --allow-mass-removal")
    if prev:                                     # re-ingest -> human report
        if added or changed or moved or removed:
            # spec/ impact: sibling of the wiki dir; changed -> wikilink,
            # removed -> plain name (the target no longer exists), moved ->
            # link under the NEW name (links to the old basename are broken)
            affected = {_nfc_fold(pages[p]["basename"]):
                        f"[[{pages[p]['basename']}|{pages[p]['title']}]]" for p in changed}
            affected.update({_nfc_fold(prev[p]["basename"]): prev[p]["title"]
                             for p in removed})
            affected.update({_nfc_fold(prev[p]["basename"]):
                             f"[[{pages[p]['basename']}|{pages[p]['title']}]]"
                             for p in moved})
            spec_dir = os.path.normpath(os.path.join(OUT, "..", "spec"))
            hits = spec_impact(spec_dir, affected) if (affected and os.path.isdir(spec_dir)) else []
            chp = os.path.join(OUT, f"_CHANGES-{snapshot or 'unknown'}.md")
            open(chp, "w", encoding="utf-8").write(
                render_changes(snapshot, pages, prev, added, changed, moved,
                               removed, hits, warns))
            print(f"[changes] +{len(added)} ~{len(changed)} →{len(moved)} "
                  f"-{len(removed)} -> {os.path.basename(chp)}"
                  + (f" (spec impact: {len(hits)} docs)" if hits else ""))
        else:
            print("[changes] no changes vs previous snapshot")
    # persist map (+content hash) + space meta for later stages (make_index.py)
    mp = {pid: dict({k: r.get(k, "") for k in ('id','title','parent','depth','order',
                                               'slug','basename','relpath','children','hash')},
                    space=SPACE)
          for pid, r in pages.items()}
    for pid, r in prev_other.items():            # other spaces keep their entries
        mp.setdefault(pid, r)
    json.dump(mp, open(os.path.join(OUT, ".pagemap.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    # per-space metadata: a wiki may hold several spaces, and Home.md dates
    # each foreign tree. The CURRENT space keeps the top-level fields (nothing
    # that reads .space.json today has to learn a new shape); `spaces` records
    # every space present in .pagemap.json.
    spaces = {}
    prev_spaces = prev_meta.get("spaces")
    if isinstance(prev_spaces, dict):
        for k, v in prev_spaces.items():
            if isinstance(v, dict):
                spaces[k] = dict(v)
    elif prev_meta.get("key"):            # .space.json of an older converter:
        spaces[prev_meta["key"]] = {      # its top-level fields are that space
            "name": prev_meta.get("name", ""),
            # 2.3 renamed the top-level date; before it the field was `snapshot`
            "snapshot_date": (prev_meta.get("snapshot_date")
                              or prev_meta.get("snapshot", "")),
            "pages": prev_meta.get("pages", 0)}
    spaces[SPACE] = {"name": name, "snapshot_date": snapshot, "pages": len(pages)}
    counts = {}
    for r in mp.values():
        counts[r.get("space") or SPACE] = counts.get(r.get("space") or SPACE, 0) + 1
    for k in list(spaces):                # a space with no pages left is gone
        if k not in counts:
            del spaces[k]
    for k, n in counts.items():
        spaces.setdefault(k, {"name": "", "snapshot_date": "", "pages": 0})["pages"] = n
    # run parameters live next to the space meta: without them the next run
    # cannot tell "the pages changed" from "you passed other flags"
    json.dump({"key": SPACE, "name": name, "base_url": BASE_URL,
               "snapshot_date": snapshot, "snapshot_date_source": snapshot_src,
               "pages": len(pages), "spaces": spaces,
               "converter_version": CONVERTER_VERSION,
               "hash_algo": HASH_ALGO, "flags": RUN_FLAGS},
              open(os.path.join(OUT, ".space.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    # machine-readable ingest report -- written on EVERY run
    ingest = {
        "snapshot_date": snapshot, "snapshot_date_source": snapshot_src,
        "space": SPACE, "base_url": BASE_URL,
        "converter_version": CONVERTER_VERSION, "flags": RUN_FLAGS,
        "flags_changed": bool(flags_warn),
        "converter_changed": bool(version_warn),
        "pages_written": n_ok,
        "added":   [{"id": p, "title": pages[p]["title"],
                     "relpath": pages[p]["relpath"]} for p in added],
        "changed": [{"id": p, "title": pages[p]["title"],
                     "relpath": pages[p]["relpath"]} for p in changed],
        "moved":   [{"id": p, "title": pages[p]["title"],
                     "from": prev[p]["relpath"], "to": pages[p]["relpath"]} for p in moved],
        "removed": [{"id": p, "title": prev[p]["title"],
                     "relpath": prev[p]["relpath"]} for p in removed],
        "table_fallbacks": fallbacks,
        "missing_assets": miss,
        "missing_links": ctx["missing_links"],
        "colour_lost": ctx.get("colour_lost", []),
        "stale_removed": stale_removed,
        "stale_blocked": stale_blocked,
    }
    json.dump(ingest, open(os.path.join(OUT, ".ingest.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

if __name__ == "__main__":
    main()
