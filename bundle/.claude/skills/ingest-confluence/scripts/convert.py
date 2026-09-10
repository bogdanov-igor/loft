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

CONVERTER_VERSION = "2.4"
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
            if "unknown-macro" in src:      # macro the export could not render:
                p = E("p")                  # dropping it silently loses content
                s = etree.SubElement(p, "strong")
                s.text = "⚠️ неизвестный макрос Confluence — содержимое не выгружено, см. страницу-источник"
                replace_with(img, p); continue
            img.getparent().remove(img); continue
        new_src = None
        if src.startswith("attachments/"):
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
    return md

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
    fix_inline = lambda s: re.sub(r"<(https?://[^>\s]+)>", auto_conf, s).replace("-\\>", "->")
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
        return m.group(0)
    md = re.sub(r'(<a\s[^>]*?)href="((?:https?:|/)[^"]+)"', html_conf, md)
    # "create page" redlinks point to nothing -> collapse to plain text
    md = re.sub(r'<a\b[^>]*href="[^"]*createpage\.action[^"]*"[^>]*>(.*?)</a>', r"\1", md, flags=re.S)
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
        "stale_removed": stale_removed,
        "stale_blocked": stale_blocked,
    }
    json.dump(ingest, open(os.path.join(OUT, ".ingest.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

if __name__ == "__main__":
    main()
