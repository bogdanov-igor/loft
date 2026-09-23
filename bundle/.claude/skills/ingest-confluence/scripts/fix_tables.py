#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fix_tables v2 -- postprocessor for ALREADY converted .md pages (no source HTML).

Brings an old wiki to what convert.py v2.2 would produce today; everything
else stays byte-for-byte, code fences, indented code blocks and inline `code`
are never touched:
1. decorative icon <img> (jira viewavatar/useravatar, emoticons, images/icons)
   are dropped -- they pin pages to a live tracker and render as broken images;
   every other raw <img> becomes markdown, the way convert.py v2.2 emits it:
   a local picture -> ![[basename]] (a sized <img> survives as raw HTML and is
   invisible both to link-check and to Obsidian -- 88 of 230 pictures in a real
   corpus; rendered size and alt are the price of a real embed), an external
   http(s) one -> ![alt](url). Inside raw fallback tables <img> stays HTML.
   The same holds in a converted GFM table: tablemd renders a cell picture as
   ![alt](path), and a local one becomes ![[basename]] -- byte-for-byte what
   convert.py writes into a cell (the alias is dropped: an embed has none);
2. empty attachment anchors <a ...></a> get visible text:
   data-linked-resource-default-alias -> aria-label -> basename(href)
   (applied inside tables and standalone; runs BEFORE the attribute scrub);
3. HTML anchors: in flow text a tag-free <a href>text</a> becomes markdown --
   href to *.md -> [[basename|text]], href to attachments/assets ->
   [[flat|text]], anything else -> [text](url) (or <url> when text == url);
   anchors inside raw <table> blocks (Obsidian can't parse wikilinks there)
   and anchors with nested tags only get their attributes scrubbed;
4. attribute scrub on remaining raw-HTML opening tags (whitelist per tag,
   same as convert.py clean_dom): class/style/rel/data-*/aria-* noise from
   Confluence exports disappears, <td colspan>, <img src alt>,
   <pre|code class>, <a href title name id> survive; unquoted and
   single-quoted attribute values are understood, not dropped. The colour
   convert.py 2.5 writes (<span|td|th style="color:#hex;background-color:
   #hex">, exactly that form) survives too -- scrubbed, it left bare <span>;
5. raw Confluence HTML <table> blocks -> GFM pipe tables via tablemd;
   fallback (kept as raw HTML, logged): colspan/rowspan (unless
   --expand-spans), nested tables, long/indented <pre> in cells, tables that
   do not start a line ("inline-table") and tables inside "> " quotes. Junk
   lines adjacent to a REPLACED block (blank runs, lone "\\" from <br/>) are
   collapsed to one blank line. Multi-line fallback blocks without <pre>
   are collapsed to ONE line (a newline inside raw HTML ends the block for
   md renderers -- the tail rendered as text). Cells that already hold
   markdown ([[link]], **bold**, `code`) are not re-escaped;
6. when <root>/.pagemap.json exists (written by convert.py), absolute
   confluence URLs that resolve to a page of this wiki (?pageId=,
   /spaces/<KEY>/pages/<id>, /x/<tiny>) become [[wikilinks]] in flow and
   note-relative hrefs inside raw tables. A URL pointing at the page ITSELF
   is never rewritten: it is the only pointer to the live Confluence page;
7. pandoc artifact repairs (verified against source exports): "-\\>" -> "->",
   broken bold "**X\\**" at end of line -> "**X**", default expand label
   "**▸ Нажмите здесь для раскрытия...**" -> "**▸ Подробнее**",
   "[!KEY](jira-url?src=confmacro)" -> "[KEY](...)";
8. a "**Источник:**" footer that an earlier version turned into a self-link
   ([[page|Confluence KEY / id]]) is restored to the Confluence URL, taken
   from the frontmatter "source:" or from .space.json base_url + page id.

Safety rules:
- only pages with "confluence_id:" in the frontmatter are processed; the
  hand-written layers living under wiki/ (_KNOWLEDGE-MAP.md, _TRAINING/,
  _specs/ ...) are left alone unless --all is given;
- a page that fails to read or process is reported and skipped, the run goes
  on and exits 1; a missing path exits 2; an unreadable .pagemap.json is a
  warning and the run continues without link resolution.

Idempotent: a second run changes 0 files.
CLI: python3 fix_tables.py <dir-or-file> [--dry-run] [--all]
                           [--unroll-pre] [--expand-spans]
--all: process md files without confluence_id too (hand-written layers).
--unroll-pre: многострочные pre-таблицы не остаются HTML, а разворачиваются --
ячейка получает «см. Пример N ниже», код выносится фенсами после таблицы.
--expand-spans: colspan/rowspan таблицы не остаются HTML -- rowspan повторяет
значение на каждой строке, colspan дополняет пропуски пустыми ячейками.
"""
import os, re, sys, html, json
import urllib.parse
import lxml.html
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tablemd

# printing Cyrillic page names must not depend on the shell locale (LC_ALL=C)
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:                              # pragma: no cover - py<3.7 / pipes
        pass

UNROLL = False        # --unroll-pre: см. docstring
EXPAND = False        # --expand-spans: см. docstring
ALL = False           # --all: обрабатывать и файлы без confluence_id

S_MARK, E_MARK = "\x00TBL\x00", "\x00/TBL\x00"

# attribute scrub whitelist -- keep in sync with convert.py KEEP_ATTRS
# ("name"/"id" on <a> are anchor targets: dropping them breaks "#anchor" links)
KEEP_ATTRS = {
    "a": ("href", "title", "name", "id"), "img": ("src", "alt"),
    "td": ("colspan", "rowspan"), "th": ("colspan", "rowspan"),
    "pre": ("class",), "code": ("class",),
    "table": (), "tbody": (), "thead": (), "tr": (), "p": (), "br": (),
    "strong": (), "em": (), "b": (), "i": (), "u": (), "s": (), "del": (),
    "ul": (), "ol": (), "li": (), "span": (), "div": (), "blockquote": (),
    "h1": (), "h2": (), "h3": (), "h4": (), "h5": (), "h6": (),
}
ICON_SRC = re.compile(r"viewavatar|useravatar|/images/emoticons/|images/icons/")
# (?<!\\): an escaped literal like "\<b\>" in cell text is NOT markup
OPEN_TAG = re.compile(r"(?<!\\)<([a-zA-Z][a-zA-Z0-9]*)((?:\s[^<>]*?)?)(/?)>")
A_SIMPLE = re.compile(r"(?<!\\)<a\b[^<>]*>([^<>]*)</a>")   # tag-free inner, one line
IMG_TAG = re.compile(r"(?<!\\)<img\b[^<>]*/?>")
CODE_SPAN = re.compile(r"`+[^`]*`+")
ATTR = re.compile(r"""([\w:-]+)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'`=<>]+))""")
# raw table blocks start a line (optionally quoted); "<table" in prose or in
# inline code is text, not markup
TBL_OPEN_LINE = re.compile(r"^[ \t]*(?:>[ \t]*)*<table\b")
INDENT_CODE = re.compile(r"^(?: {4}|\t)")
LIST_ITEM = re.compile(r"^[ \t]*(?:[-*+]|\d+[.)])[ \t]")
FM = re.compile(r"(?s)\A---\n(.*?)\n---\n")
WIKILINK = re.compile(r"(?<!\\)\[\[([^\]\n]*)\]\]")


# ---------------------------------------------------------------- masking
def fence_lines(lines):
    """Line indexes inside ``` / ~~~ fences (incl. the fence lines)."""
    masked, in_f = set(), False
    for i, l in enumerate(lines):
        if re.match(r"^[ \t]*(```|~~~)", l):
            masked.add(i); in_f = not in_f
        elif in_f:
            masked.add(i)
    return masked


def indent_code_lines(lines, fenced):
    """Line indexes of 4-space/tab indented code blocks (CommonMark-ish: the
    block starts after a blank line and not as a continuation of a list item).
    Such blocks hold verbatim text -- anchors, <table>, "-\\>" inside them are
    content, not markup."""
    masked, prev, blank, i, n = set(), "", True, 0, len(lines)
    while i < n:
        l = lines[i]
        if i in fenced:
            prev, blank, i = l, False, i + 1
            continue
        if not l.strip():
            blank, i = True, i + 1
            continue
        starts = (blank and INDENT_CODE.match(l)
                  and not LIST_ITEM.match(prev) and not re.match(r"^[ \t]{2}", prev))
        if starts:
            j, last = i, i
            while j < n and j not in fenced and (
                    not lines[j].strip() or INDENT_CODE.match(lines[j])):
                if lines[j].strip():
                    last = j
                j += 1
            masked.update(range(i, last + 1))
            prev, blank, i = lines[last], False, last + 1
            continue
        prev, blank, i = l, False, i + 1
    return masked


def masked_lines(lines):
    """Line indexes of verbatim regions: fences + indented code blocks."""
    fenced = fence_lines(lines)
    return fenced | indent_code_lines(lines, fenced)


def code_spans(text):
    """[start, end) char ranges of the verbatim regions of masked_lines()."""
    lines = text.split("\n")
    m = masked_lines(lines)
    spans, pos = [], 0
    for i, l in enumerate(lines):
        if i in m:
            spans.append((pos, pos + len(l) + 1))
        pos += len(l) + 1
    return spans


def sub_outside_code(line, fn):
    """Apply fn(segment)->segment to the parts of a line outside `code spans`."""
    out, pos = [], 0
    for m in CODE_SPAN.finditer(line):
        out.append(fn(line[pos:m.start()]))
        out.append(m.group(0))
        pos = m.end()
    out.append(fn(line[pos:]))
    return "".join(out)


def outside_code(line):
    """Segments of a line outside `code spans` (read-only walk)."""
    pos = 0
    for m in CODE_SPAN.finditer(line):
        yield line[pos:m.start()]
        pos = m.end()
    yield line[pos:]


def _in_code_span(line, pos):
    for m in CODE_SPAN.finditer(line):
        if m.start() <= pos < m.end():
            return True
    return False


# ---------------------------------------------------------------- page identity
def page_meta(text, relname):
    """Frontmatter facts needed to keep a page from linking to itself."""
    fm = FM.match(text)
    body = fm.group(1) if fm else ""
    cid = re.search(r"(?m)^confluence_id:\s*(\d+)\s*$", body)
    src = re.search(r"(?m)^source:\s*(\S+)\s*$", body)
    name = os.path.basename(relname)
    return {"name": name[:-3] if name.endswith(".md") else name,
            "rel": os.path.normpath(relname),
            "id": cid.group(1) if cid else "",
            "src": src.group(1) if src else ""}


def has_confluence_id(text):
    fm = FM.match(text)
    return bool(fm and re.search(r"(?m)^confluence_id:\s*\d+\s*$", fm.group(1)))


def fix_empty_anchors_text(text):
    """Insert fallback text into <a ...></a> (raw markdown text level)."""
    lines = text.split("\n")
    masked = masked_lines(lines)

    def sub(m):
        try:
            el = lxml.html.fromstring(m.group(0))
        except Exception:
            return m.group(0)
        if el.tag != "a" or not el.get("href"):
            return m.group(0)
        txt = tablemd.anchor_fallback_text(el)
        if not txt:
            return m.group(0)
        # "|" would split a pipe-table cell; entity renders identically
        safe = html.escape(txt).replace("|", "&#124;")
        return m.group(0)[:-len("</a>")] + safe + "</a>"

    for i, l in enumerate(lines):
        if i in masked or "></a>" not in l:
            continue
        lines[i] = sub_outside_code(
            l, lambda s: re.sub(r"(?<!\\)<a\b[^>]*></a>", sub, s))
    return "\n".join(lines)


# ---------------------------------------------------------------- pagemap
def load_pagemap(base):
    """<base>/.pagemap.json (written by convert.py) -> {id: (basename, relpath)}."""
    path = os.path.join(base, ".pagemap.json")
    if not os.path.exists(path):
        return {}
    try:
        pm = json.load(open(path, encoding="utf-8"))
        return {pid: (r["basename"], r["relpath"]) for pid, r in pm.items()
                if r.get("basename") and r.get("relpath")}
    except Exception as e:
        print(f"[warn] .pagemap.json unreadable ({e.__class__.__name__}): "
              f"confluence URLs will not resolve")
        return {}


def load_space(base):
    """<base>/.space.json -> {"key": ..., "base_url": ...} (may be empty)."""
    path = os.path.join(base, ".space.json")
    if not os.path.exists(path):
        return {}
    try:
        sp = json.load(open(path, encoding="utf-8"))
        return {"key": str(sp.get("key") or ""),
                "base_url": str(sp.get("base_url") or "").rstrip("/")}
    except Exception as e:
        print(f"[warn] .space.json unreadable ({e.__class__.__name__})")
        return {}


def conf_page(url, pagemap):
    """Absolute confluence URL -> (basename, relpath) of a wiki page, or None."""
    if not pagemap:
        return None
    u = html.unescape(url)
    m = re.search(r"[?&]pageId=(\d+)", u)
    if m and m.group(1) in pagemap:
        return pagemap[m.group(1)]
    m = re.search(r"/spaces/[^/]+/pages/(\d+)(?:[/?#]|$)", u)
    if m and m.group(1) in pagemap:
        return pagemap[m.group(1)]
    m = re.search(r"/x/([A-Za-z0-9_\-]+)", u)
    if m:
        for pid in tablemd.decode_tiny(m.group(1)):
            if pid in pagemap:
                return pagemap[pid]
    return None


def conf_link(url, pagemap, page):
    """conf_page(), but a URL pointing at THIS page is not a link target: the
    footer "Источник" and any self-reference must keep the Confluence URL --
    it is the only way back to the live page."""
    hit = conf_page(url, pagemap)
    if not page:
        return hit
    u = html.unescape(url)
    m = re.search(r"[?&]pageId=(\d+)|/spaces/[^/]+/pages/(\d+)", u)
    pid = (m.group(1) or m.group(2)) if m else ""
    if pid and page.get("id") and pid == page["id"]:
        return None
    if hit and (hit[0] == page.get("name")
                or os.path.normpath(hit[1]) == page.get("rel")):
        return None
    return hit


# ---------------------------------------------------------------- source footer
SRC_FOOT = re.compile(
    r"(?m)^(\*\*Источник:\*\*[ \t]*)\[\[([^\]|\n]+?)(?:\|([^\]\n]+?))?\]\]([ \t]*)$")


def restore_source_footer(text, page, space):
    """'**Источник:** [[self|Confluence KEY / id]]' -> '[Confluence KEY / id](url)'.
    An earlier version resolved the footer URL against the pagemap and produced
    a link to the page itself, losing the pointer to the live Confluence page.
    URL: frontmatter "source:", else .space.json base_url + page id."""
    spans = code_spans(text)

    def sub(m):
        if any(a <= m.start() < b for a, b in spans):
            return m.group(0)
        target = m.group(2).split("#")[0].strip()
        if target != page.get("name"):             # a link elsewhere: not ours
            return m.group(0)
        alias = (m.group(3) or "").strip()
        pid = page.get("id") or ""
        if not pid:
            d = re.search(r"(\d+)\s*$", alias)
            pid = d.group(1) if d else ""
        url = page.get("src") or ""
        base = (space or {}).get("base_url", "")
        if not url and base and pid:
            url = f"{base}/pages/viewpage.action?pageId={pid}"
        key = (space or {}).get("key", "")
        label = alias or (f"Confluence {key} / {pid}" if key and pid else "")
        if not url or not label:
            return m.group(0)
        return f"{m.group(1)}[{label}]({url}){m.group(4)}"

    return SRC_FOOT.sub(sub, text)


# ---------------------------------------------------------------- anchors/imgs
def drop_icon_imgs(text):
    """Remove decorative avatar/emoticon <img> tags (jira macro icons)."""
    lines = text.split("\n")
    masked = masked_lines(lines)

    def seg(s):
        def one(m):
            a = _attrs(m.group(0))
            return "" if ICON_SRC.search(a.get("src", "")) else m.group(0)
        return IMG_TAG.sub(one, s)

    for i, l in enumerate(lines):
        if i in masked or "<img" not in l:
            continue
        lines[i] = sub_outside_code(l, seg)
    return "\n".join(lines)


def _attrs(s):
    """Attributes of a raw tag: double-, single- and unquoted values."""
    out = {}
    for m in ATTR.finditer(s):
        v = next(x for x in m.group(2, 3, 4) if x is not None)
        out.setdefault(m.group(1).lower(), v)
    return out


def _table_spans(text):
    """[start, end) of balanced raw <table> blocks, wherever they start (a
    fallback block collapsed to one line included). Verbatim regions and
    inline code do not open a block."""
    spans, pos, masked = [], 0, code_spans(text)
    for m in re.finditer(r"(?<!\\)<table\b", text):
        i = m.start()
        if i < pos or any(a <= i < b for a, b in masked):
            continue
        ls = text.rfind("\n", 0, i) + 1
        le = text.find("\n", i)
        le = len(text) if le < 0 else le
        if _in_code_span(text[ls:le], i - ls):
            continue
        depth, j = 0, None
        for mm in re.finditer(r"<table\b|</table>", text[i:]):
            depth += 1 if not mm.group(0).startswith("</") else -1
            if depth == 0:
                j = i + mm.end()
                break
        if j is None:                             # unbalanced -> not a block
            continue
        spans.append((i, j))
        pos = j
    return spans


def imgs_to_md(text):
    """Raw <img> -> markdown, exactly as convert.py v2.2 emits it: a local
    picture (src without an http(s)/data scheme) becomes ![[basename]], an
    external http(s) one becomes ![alt](url). A sized <img> stays raw HTML
    through pandoc, so neither link-check nor Obsidian sees the picture --
    the rendered size and the alt text are the price of a real embed.
    Untouched: fences, indented code, inline code and raw fallback <table>
    blocks (Obsidian does not parse embeds inside raw HTML). Decorative icons
    are already gone -- drop_icon_imgs runs earlier."""
    lines = text.split("\n")
    masked = masked_lines(lines)
    tables = _table_spans(text)
    pos = 0
    for i, l in enumerate(lines):
        start, end = pos, pos + len(l)
        pos = end + 1
        if i in masked or "<img" not in l:
            continue
        if any(a < end and start < b for a, b in tables):
            continue
        pipe_row = bool(re.match(r"^[ \t]*\|", l))

        def one(m):
            attrs = _attrs(m.group(0))
            src = html.unescape(attrs.get("src", "")).strip()
            if not src:
                return m.group(0)
            if re.match(r"https?:", src, re.I):
                alt = re.sub(r"\s+", " ", html.unescape(attrs.get("alt", "")))
                alt = re.sub(r"([\\\[\]])", r"\\\1", alt.strip())
                if pipe_row:
                    alt = alt.replace("|", "\\|")
                return f"![{alt}]({tablemd.esc_url(src)})"
            if re.match(r"[a-zA-Z][a-zA-Z0-9+.-]*:", src):   # data:, mailto: ...
                return m.group(0)
            flat = os.path.basename(
                urllib.parse.unquote(src.split("#")[0].split("?")[0]))
            return f"![[{flat}]]" if flat else m.group(0)

        lines[i] = sub_outside_code(l, lambda seg: IMG_TAG.sub(one, seg))
    return "\n".join(lines)


# картинка в ячейке GFM-таблицы: tablemd рендерит <img> как ![alt](src)
# (title tablemd не пишет, но старая ячейка могла нести его сама)
MD_IMG = re.compile(
    r"(?<!\\)!\[((?:[^\[\]\\\n]|\\.)*)\]\("
    r"(?:<([^<>\n]*)>|([^()\s]*))"
    r"""(?:[ \t]+(?:"[^"\n]*"|'[^'\n]*'|\([^()\n]*\)))?\)""")


def tbl_imgs_to_embeds(text):
    """Локальная md-картинка в строке GFM-таблицы -> ![[basename]], как в
    потоке и как у convert.py: tablemd отдаёт ячейку с ![alt](путь), а корпус
    держит картинки embed'ами (их видят link-check и Obsidian). Внешняя
    http(s)/data-картинка остаётся md-картинкой. Алиас не переносится: у
    embed'а его нет — заодно исчезает и экранированный \\| внутри alt.
    Фенсы, отступной код и инлайн-код не трогаются; сырые fallback-таблицы
    строк с «|» не дают, их <img> остаётся HTML."""
    lines = text.split("\n")
    masked = masked_lines(lines)

    def one(m):
        src = m.group(2) if m.group(2) is not None else m.group(3)
        src = html.unescape(src or "").strip()
        if not src or re.match(r"[a-zA-Z][a-zA-Z0-9+.-]*:", src):
            return m.group(0)                     # http(s):, data:, mailto: ...
        flat = os.path.basename(
            urllib.parse.unquote(src.split("#")[0].split("?")[0]))
        return f"![[{flat}]]" if flat else m.group(0)

    for i, l in enumerate(lines):
        if i in masked or "![" not in l or not re.match(r"^[ \t]*\|", l):
            continue
        lines[i] = sub_outside_code(l, lambda s: MD_IMG.sub(one, s))
    return "\n".join(lines)


def _scrub_open_tags(segment):
    """Whitelist-scrub attributes of raw-HTML opening tags in a text segment.
    style survives on span/td/th ONLY in the form convert.py 2.5 writes for
    colour (tablemd.canon_style): Confluence's own style noise still goes."""
    def sub(m):
        tag, attrs_s, selfc = m.group(1).lower(), m.group(2) or "", m.group(3)
        keep = KEEP_ATTRS.get(tag)
        if keep is None:                          # unknown tag -> not our HTML
            return m.group(0)
        attrs = _attrs(attrs_s)
        if tag in ("span", "td", "th") and tablemd.canon_style(attrs.get("style")):
            keep = keep + ("style",)
        kept = "".join((f" {k}='{attrs[k]}'" if '"' in attrs[k]
                        else f' {k}="{attrs[k]}"') for k in keep if k in attrs)
        return f"<{tag}{kept}{'/' if selfc else ''}>"
    return OPEN_TAG.sub(sub, segment)


def _anchor_to_md(inner, attrs_s, pipe_row, pagemap=None, page=None):
    """<a ...>inner</a> (tag-free inner) -> markdown, or None to keep HTML."""
    href = _attrs(attrs_s).get("href")
    if href is None:
        return None
    href = html.unescape(href)
    text = re.sub(r"\s+", " ", html.unescape(inner)).replace("\xa0", " ").strip()
    text = re.sub(r"^\*\*(.+)\*\*$", r"\1", text)  # bold-wrapped link text
    if "|" in text or "]]" in text or "[[" in text:
        return None                               # scrub-only is safer
    text_is_url = bool(re.match(r"https?://", text))
    scheme = re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", href)
    sep = "\\|" if pipe_row else "|"
    if not scheme and not href.startswith(("/", "#")):
        path = urllib.parse.unquote(href.split("#")[0].split("?")[0])
        base = os.path.basename(path)
        if base.endswith(".md"):                  # internal page -> wikilink
            name = base[:-3]
            if not text or text == name:
                return f"[[{name}]]"
            if text_is_url:                       # pasted URL as link text:
                hit = conf_page(text, pagemap)    # page name says more
                mpid = re.search(r"pageId=(\d+)", text)
                if (hit and hit[0] == name) or (mpid and name.endswith("-" + mpid.group(1))):
                    return f"[[{name}]]"
            return f"[[{name}{sep}{text}]]"
        if "attachments/" in path or "assets/" in path:
            return f"[[{base}]]" if (not text or text == base) else f"[[{base}{sep}{text}]]"
    if scheme and re.match(r"https?://", href):   # confluence URL -> wikilink
        hit = conf_link(href, pagemap, page)      # (never for a self-link)
        if hit:
            name = hit[0]
            if (not text or text == name or text == href
                    or (text_is_url and conf_page(text, pagemap) == hit)):
                return f"[[{name}]]"
            return f"[[{name}{sep}{text}]]"
    url = tablemd.esc_url(href)
    if not text or text == href:
        return f"<{url}>"
    if pipe_row:
        text = text.replace("|", "\\|")
    text = re.sub(r"([\\`*_\[\]<])", r"\\\1", text)
    return f"[{text}]({url})"


def clean_anchors(text, pagemap=None, relname="", page=None):
    """Flow anchors -> markdown; anchors in raw <table> blocks and anchors
    with nested tags -> attribute scrub only (confluence hrefs inside tables
    are rewritten to note-relative paths when the pagemap knows them).
    Raw-table element tags (td, p, ...) are attribute-scrubbed too.
    Fences, indented code and inline code stay untouched."""
    lines = text.split("\n")
    masked = masked_lines(lines)
    here = os.path.dirname(relname)
    depth = 0
    for i, l in enumerate(lines):
        if i in masked:
            continue
        # only a line that STARTS with "<table" opens a raw table block --
        # "<table" mentioned in prose or inline code used to switch the whole
        # rest of the file to scrub-only mode
        in_tbl = depth > 0 or bool(TBL_OPEN_LINE.match(l))
        if in_tbl:
            depth += len(re.findall(r"<table\b", l)) - l.count("</table>")
            if depth < 0:
                depth = 0
        if "<" not in l:
            continue
        pipe_row = bool(re.match(r"^[ \t]*\|", l))

        def loc(m):
            hit = conf_link(m.group(1), pagemap, page)
            if not hit:
                return m.group(0)
            rel = os.path.relpath(hit[1], here) if here else hit[1]
            return f'href="{urllib.parse.quote(rel)}"'

        def seg(s):
            if not in_tbl:                        # flow: try full conversion
                # bold/italic INSIDE a link is decoration (the link is the
                # emphasis); md/wikilink alias renders "**" literally -> strip
                s = re.sub(
                    r"(?<!\\)(<a\b[^<>]*>)((?:[^<>]|</?(?:strong|em|b|i)\s*/?>)*?)</a>",
                    lambda m: m.group(1)
                    + re.sub(r"</?(?:strong|em|b|i)\s*/?>", "", m.group(2))
                    + "</a>", s)
                def conv(m):
                    am = re.match(r"<a\b((?:\s[^<>]*?)?)>", m.group(0))
                    if not am:
                        return m.group(0)
                    md = _anchor_to_md(m.group(1), am.group(1), pipe_row, pagemap, page)
                    return md if md is not None else m.group(0)
                s = A_SIMPLE.sub(conv, s)
            if "<" in s:                          # leftovers: scrub attributes
                s = _scrub_open_tags(s)
            if in_tbl and pagemap:                # in tables: localize hrefs
                s = re.sub(r'href="(https?://[^"]+)"', loc, s)
            return s

        lines[i] = sub_outside_code(l, seg)
    return "\n".join(lines)


def conf_links_to_wikilinks(text, pagemap, page=None):
    """Flow markdown links/autolinks with absolute confluence URLs that
    resolve via the pagemap -> [[wikilinks]] (alias kept unless it is the
    URL itself or the page name). A link to the page itself keeps its URL."""
    if not pagemap:
        return text
    lines = text.split("\n")
    masked = masked_lines(lines)
    for i, l in enumerate(lines):
        if i in masked or "http" not in l:
            continue
        pipe_row = bool(re.match(r"^[ \t]*\|", l))
        sep = "\\|" if pipe_row else "|"

        def seg(s):
            def sub_link(m):
                text_in, url = m.group(1).strip(), m.group(2)
                hit = conf_link(url, pagemap, page)
                if not hit:
                    return m.group(0)
                name = hit[0]
                plain = text_in.replace("\\|", "|")
                if (not plain or plain == name or plain == url
                        or (re.match(r"https?://", plain)
                            and conf_page(plain, pagemap) == hit)):
                    return f"[[{name}]]"
                if "[[" in plain or "]]" in plain or ("|" in plain and not pipe_row):
                    return m.group(0)
                return f"[[{name}{sep}{text_in}]]"
            s = re.sub(r"(?<!!)\[([^\]\n]*)\]\((https?://[^)\s]+)\)", sub_link, s)
            s = re.sub(r"<(https?://[^>\s]+)>",
                       lambda m: f"[[{conf_link(m.group(1), pagemap, page)[0]}]]"
                       if conf_link(m.group(1), pagemap, page) else m.group(0), s)
            return s

        lines[i] = sub_outside_code(l, seg)
    return "\n".join(lines)


def repair_artifacts(text):
    """Pandoc artifact repairs, verified against source exports (see module
    docstring, item 7). Outside fences and indented code; inline code untouched."""
    lines = text.split("\n")
    masked = masked_lines(lines)
    for i, l in enumerate(lines):
        if i in masked:
            continue
        n = l
        n = n.replace("**▸ Нажмите здесь для раскрытия...**", "**▸ Подробнее**")
        n = n.replace("**▸ Click here to expand...**", "**▸ Подробнее**")
        if "-\\>" in n:
            n = sub_outside_code(n, lambda s: s.replace("-\\>", "->"))
        if "[!" in n:
            n = sub_outside_code(n, lambda s: re.sub(
                r"\[!([A-Za-z][A-Za-z0-9]*-\d+)\]\((https?://[^)\s]*src=confmacro[^)\s]*)\)",
                r"[\1](\2)", s))
        # broken bold from <strong>X<br/></strong>: "**X\**" at end of line;
        # (?<!\*) keeps legitimately escaped "...\*\*" (literal stars) intact
        m = re.search(r"(?<!\\\*)(?<!\*)( ?)\\\*\*$", n)
        if m and not _in_code_span(n, m.start()):
            n = n[:m.start()] + "**"
        lines[i] = n
    return "\n".join(lines)


MD_LINK_MD = re.compile(r"(?<!!)\[([^\]\n]*)\]\(([^)\s:]+\.md)(#[^)]*)?\)")
# attachment/asset links produced by tablemd inside a converted table
MD_LINK_AT = re.compile(r"(?<!!)\[([^\]\n]*)\]\((?![a-zA-Z][a-zA-Z0-9+.-]*:|/)"
                        r"([^)\s]*(?:attachments|assets)/[^)\s]+)\)")


def mdlinks_to_wikilinks(text, relname=""):
    """Relative [text](path.md) -> [[basename|text]] and
    [name](../attachments/file) -> [[file|name]] (corpus convention).
    Fresh convert.py output has none; they appear when an old-wiki table with
    internal links is converted (tablemd renders links as [text](href)).
    A path leading OUT of the wiki root keeps its markdown link: a basename
    wikilink there would point at a page that does not exist."""
    lines = text.split("\n")
    masked = masked_lines(lines)
    here = os.path.dirname(relname)

    def escapes_root(path):
        if not relname:
            return False
        tgt = os.path.normpath(os.path.join(here, urllib.parse.unquote(path)))
        return tgt.startswith("..")

    for i, l in enumerate(lines):
        if i in masked or "](" not in l:
            continue
        pipe_row = bool(re.match(r"^[ \t]*\|", l))

        def wl(base, text_in):
            plain = text_in.replace("\\|", "|").strip()   # human alias text
            if not plain or plain == base:
                return f"[[{base}]]"
            if pipe_row:
                return f"[[{base}\\|{plain.replace('|', chr(92) + '|')}]]"
            if "|" in plain:                  # would split [[target|alias]]
                return None
            return f"[[{base}|{plain}]]"

        def seg(s):
            def sub_md(m):
                text_in, path = m.group(1), m.group(2)
                if (path.startswith("/") or "]]" in text_in or "[[" in text_in
                        or escapes_root(path)):
                    return m.group(0)
                base = os.path.basename(urllib.parse.unquote(path))[:-3]
                return wl(base, text_in) or m.group(0)

            def sub_at(m):
                text_in, path = m.group(1), m.group(2)
                if "]]" in text_in or "[[" in text_in:
                    return m.group(0)
                flat = os.path.basename(
                    urllib.parse.unquote(path.split("#")[0].split("?")[0]))
                if not flat:
                    return m.group(0)
                return wl(flat, text_in) or m.group(0)

            return MD_LINK_AT.sub(sub_at, MD_LINK_MD.sub(sub_md, s))

        lines[i] = sub_outside_code(l, seg)
    return "\n".join(lines)


def count_wikilinks(text, selfname=""):
    """Honest [[wikilink]] count: fences, indented code, inline code and
    escaped \\[\\[ are not links, and a link to the page itself is not one
    either (it used to inflate the before/after report)."""
    lines = text.split("\n")
    masked = masked_lines(lines)
    n = 0
    for i, l in enumerate(lines):
        if i in masked or "[[" not in l:
            continue
        for s in outside_code(l):
            for m in WIKILINK.finditer(s):
                tgt = m.group(1).split("|")[0].split("#")[0].replace("\\", "").strip()
                if selfname and tgt == selfname:
                    continue
                n += 1
    return n


# ---------------------------------------------------------------- tables
def convert_tables(text, relname, log):
    """Replace raw <table> blocks with GFM tables (markers first, cleanup after).
    A block must start a line (or follow another block on the same line); a
    table starting mid-line is left as HTML and logged instead of silently
    surviving, and a "<table" in prose or inline code is not a table at all."""
    spans = code_spans(text)
    masked = lambda i: any(a <= i < b for a, b in spans)
    reps, pos = [], 0
    for m in re.finditer(r"(?<!\\)<table\b", text):
        i = m.start()
        if i < pos or masked(i):
            continue
        ls = text.rfind("\n", 0, i) + 1
        le = text.find("\n", i)
        le = len(text) if le < 0 else le
        if _in_code_span(text[ls:le], i - ls):    # `<table>` in inline code
            continue
        head = text[ls:i]
        depth, j = 0, None
        for mm in re.finditer(r"<table\b|</table>", text[i:]):
            depth += 1 if not mm.group(0).startswith("</") else -1
            if depth == 0:
                j = i + mm.end()
                break
        if j is None:                             # unbalanced -> not a real block
            continue
        quoted = bool(re.fullmatch(r"[ \t]*(?:>[ \t]*)+", head))
        # a block may also start right after the previous one on the same line
        if head.strip() and not (pos > ls and not text[pos:i].strip()):
            log.append((relname, "blockquote-table" if quoted else "inline-table"))
            pos = j
            continue
        pos = j                                   # skip nested opens inside block
        try:
            el = lxml.html.fromstring(text[i:j])
            if el.tag != "table":
                el = el.find(".//table")
            if el is None:
                raise tablemd.Fallback("unparseable")
            gfm = tablemd.table_to_gfm(el, indent=head if not head.strip() else "",
                                       unroll_pre=UNROLL, expand_spans=EXPAND,
                                       md_cells=True)
        except tablemd.Fallback as fb:
            log.append((relname, fb.reason))
            blk = text[i:j]
            # multi-line raw HTML block: md renderers end the block at the
            # first blank/loose line and print the tail as text -> collapse
            # to one line (except <pre>: its newlines are content)
            if "\n" in blk and "<pre" not in blk:
                reps.append((i, j, re.sub(r"\s*\n\s*", " ", blk).strip(), False))
            continue
        reps.append((i, j, gfm, True))
    if not reps:
        return text, 0
    out, cur = [], 0
    for i, j, gfm, _conv in reps:
        gap = text[cur:i]
        if cur and not gap.strip() and "\n" not in gap:
            gap = "\n"                            # two tables on one line
        out.append(gap)
        out.append(S_MARK + "\n" + gfm + "\n" + E_MARK)
        cur = j
    out.append(text[cur:])
    return _cleanup_markers("".join(out)), sum(1 for r in reps if r[3])


def _cleanup_markers(text):
    """Around each replaced block: exactly one blank line, drop lone-"\\" lines."""
    lines, res, i = text.split("\n"), [], 0
    junk = lambda l: l.strip() in ("", "\\")
    while i < len(lines):
        if lines[i] == S_MARK:
            while res and junk(res[-1]):
                res.pop()
            if res:
                res.append("")
            i += 1
            while i < len(lines) and not lines[i].startswith(E_MARK):
                res.append(lines[i]); i += 1
            rest = lines[i][len(E_MARK):] if i < len(lines) else ""
            i += 1
            while i < len(lines) and junk(lines[i]):
                i += 1
            res.append("")
            if rest.strip():                      # text after </table> on same line
                res.append(rest)
            continue
        res.append(lines[i]); i += 1
    return "\n".join(res)


def process_text(old, relname, log, pagemap=None, space=None):
    page = page_meta(old, relname)
    new = restore_source_footer(old, page, space)
    new = drop_icon_imgs(new)
    new = fix_empty_anchors_text(new)             # needs data-* attrs: before scrub
    new = clean_anchors(new, pagemap, relname, page)
    new, n_tbl = convert_tables(new, relname, log)
    new = imgs_to_md(new)                         # after: fallback tables keep <img>
    new = tbl_imgs_to_embeds(new)                 # ячейки GFM: ![alt](x) -> ![[x]]
    new = mdlinks_to_wikilinks(new, relname)
    new = conf_links_to_wikilinks(new, pagemap, page)
    new = repair_artifacts(new)
    return new, n_tbl, page


def wiki_root(start):
    """Nearest ancestor holding .pagemap.json -- so a single file deep in the
    tree still resolves confluence links (and gets its true relpath)."""
    d = os.path.abspath(start or ".")
    for _ in range(16):
        if os.path.exists(os.path.join(d, ".pagemap.json")):
            return d
        up = os.path.dirname(d)
        if up == d:
            break
        d = up
    return os.path.abspath(start or ".")


def main():
    global UNROLL, EXPAND, ALL
    flags = ("--dry-run", "--unroll-pre", "--expand-spans", "--all")
    args = [a for a in sys.argv[1:] if a not in flags]
    bad = [a for a in args if a.startswith("--")]
    dry = "--dry-run" in sys.argv[1:]
    UNROLL = "--unroll-pre" in sys.argv[1:]
    EXPAND = "--expand-spans" in sys.argv[1:]
    ALL = "--all" in sys.argv[1:]
    if len(args) != 1 or bad:
        print("usage: fix_tables.py <dir-or-file> [--dry-run] [--all] "
              "[--unroll-pre] [--expand-spans]", file=sys.stderr)
        if bad:
            print(f"[error] unknown flag: {' '.join(bad)}", file=sys.stderr)
        sys.exit(2)
    root = args[0]
    if not os.path.exists(root):
        print(f"[error] path not found: {root}", file=sys.stderr)
        sys.exit(2)
    if os.path.isfile(root):
        files = [root]
        base = wiki_root(os.path.dirname(os.path.abspath(root)))
    else:
        base = wiki_root(root)
        files = []
        for dirpath, _, names in os.walk(root):
            files += [os.path.join(dirpath, n) for n in sorted(names) if n.endswith(".md")]
    pagemap = load_pagemap(base)
    space = load_space(base)
    if pagemap:
        print(f"[pagemap] {len(pagemap)} pages known -- confluence URLs will resolve")
    log, n_changed, n_tables, n_seen, n_skip, n_err = [], 0, 0, 0, 0, 0
    n_wl_old = n_wl_new = 0                       # wikilink counters (sanity print)
    for f in sorted(files):
        rel = os.path.relpath(f, base)
        try:
            old = open(f, encoding="utf-8").read()
        except (UnicodeDecodeError, OSError) as e:
            print(f"[error] {rel}: {e.__class__.__name__}: {e}")
            n_err += 1
            continue
        if not ALL and not has_confluence_id(old):
            n_skip += 1                           # hand-written layer -> never touch
            continue
        n_seen += 1
        try:
            new, n_tbl, page = process_text(old, rel, log, pagemap, space)
        except Exception as e:
            print(f"[error] {rel}: {e.__class__.__name__}: {e}")
            n_err += 1
            continue
        n_wl_old += count_wikilinks(old, page["name"])
        n_wl_new += count_wikilinks(new, page["name"])
        if new != old:
            n_changed += 1
            n_tables += n_tbl
            print(f"[fix] {rel}: {n_tbl} table(s) converted"
                  + (", anchors/cleanup" if n_tbl == 0 else ""))
            if not dry:
                try:
                    open(f, "w", encoding="utf-8").write(new)
                except OSError as e:
                    print(f"[error] {rel}: write failed: {e}")
                    n_err += 1
    for rel, reason in log:
        print(f"[fallback] {rel}: {reason}")
    if n_skip:
        print(f"[skip] {n_skip} file(s) without confluence_id (hand-written; --all)")
    if n_err:
        print(f"[errors] {n_err} file(s) skipped")
    print(f"[wikilinks] {n_wl_old} -> {n_wl_new}")
    print(f"[done] {n_changed}/{n_seen} files changed, {n_tables} tables converted, "
          f"{len(log)} fallbacks{' (dry-run)' if dry else ''}")
    sys.exit(1 if n_err else 0)


if __name__ == "__main__":
    main()
