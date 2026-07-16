#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fix_tables v2 -- postprocessor for ALREADY converted .md pages (no source HTML).

Brings an old wiki to what convert.py v2.1 would produce today; everything
else stays byte-for-byte, code fences and inline `code` are never touched:
1. decorative icon <img> (jira viewavatar/useravatar, emoticons, images/icons)
   are dropped -- they pin pages to a live tracker and render as broken images;
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
   Confluence exports disappears, <td colspan>, <img src alt width height>,
   <pre|code class> survive;
5. raw Confluence HTML <table> blocks -> GFM pipe tables via tablemd;
   fallback (kept as raw HTML, logged): colspan/rowspan (unless
   --expand-spans), nested tables, long/indented <pre> in cells. Junk lines
   adjacent to a REPLACED block (blank runs, lone "\\" from <br/>) are
   collapsed to one blank line. Multi-line fallback blocks without <pre>
   are collapsed to ONE line (a newline inside raw HTML ends the block for
   md renderers -- the tail rendered as text);
6. when <root>/.pagemap.json exists (written by convert.py), absolute
   confluence URLs that resolve to a page of this wiki (?pageId=,
   /spaces/<KEY>/pages/<id>, /x/<tiny>) become [[wikilinks]] in flow and
   note-relative hrefs inside raw tables;
7. pandoc artifact repairs (verified against source exports): "-\\>" -> "->",
   broken bold "**X\\**" at end of line -> "**X**", default expand label
   "**▸ Нажмите здесь для раскрытия...**" -> "**▸ Подробнее**",
   "[!KEY](jira-url?src=confmacro)" -> "[KEY](...)".

Idempotent: a second run changes 0 files.
CLI: python3 fix_tables.py <dir-or-file> [--dry-run] [--unroll-pre] [--expand-spans]
--unroll-pre: multiline-pre таблицы не остаются HTML, а разворачиваются --
ячейка получает «см. Пример N ниже», код выносится фенсами после таблицы.
--expand-spans: colspan/rowspan таблицы не остаются HTML -- rowspan повторяет
значение на каждой строке, colspan дополняет пропуски пустыми ячейками.
"""
import os, re, sys, html, json
import urllib.parse
import lxml.html
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tablemd

UNROLL = False        # --unroll-pre: см. docstring
EXPAND = False        # --expand-spans: см. docstring

S_MARK, E_MARK = "\x00TBL\x00", "\x00/TBL\x00"

# attribute scrub whitelist -- keep in sync with convert.py KEEP_ATTRS
KEEP_ATTRS = {
    "a": ("href", "title"), "img": ("src", "alt", "width", "height"),
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
CODE_SPAN = re.compile(r"`+[^`]*`+")


def fence_spans(text):
    """[start, end) char ranges of ``` / ~~~ fenced code blocks."""
    spans, start, pos, in_fence = [], 0, 0, False
    for line in text.split("\n"):
        if re.match(r"^[ \t]*(```|~~~)", line):
            if not in_fence:
                in_fence, start = True, pos
            else:
                in_fence = False
                spans.append((start, pos + len(line) + 1))
        pos += len(line) + 1
    if in_fence:                                  # unclosed fence -> protect to EOF
        spans.append((start, len(text)))
    return spans


def fence_lines(lines):
    """Line indexes inside ``` / ~~~ fences (incl. the fence lines)."""
    masked, in_f = set(), False
    for i, l in enumerate(lines):
        if re.match(r"^[ \t]*(```|~~~)", l):
            masked.add(i); in_f = not in_f
        elif in_f:
            masked.add(i)
    return masked


def sub_outside_code(line, fn):
    """Apply fn(segment)->segment to the parts of a line outside `code spans`."""
    out, pos = [], 0
    for m in CODE_SPAN.finditer(line):
        out.append(fn(line[pos:m.start()]))
        out.append(m.group(0))
        pos = m.end()
    out.append(fn(line[pos:]))
    return "".join(out)


def fix_empty_anchors_text(text):
    """Insert fallback text into <a ...></a> (raw markdown text level)."""
    spans = fence_spans(text)

    def sub(m):
        if any(a <= m.start() < b for a, b in spans):
            return m.group(0)
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

    return re.sub(r"<a\b[^>]*></a>", sub, text)


# ---------------------------------------------------------------- pagemap
def load_pagemap(base):
    """<base>/.pagemap.json (written by convert.py) -> {id: (basename, relpath)}."""
    try:
        pm = json.load(open(os.path.join(base, ".pagemap.json"), encoding="utf-8"))
        return {pid: (r["basename"], r["relpath"]) for pid, r in pm.items()
                if r.get("basename") and r.get("relpath")}
    except Exception:
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


# ---------------------------------------------------------------- anchors/imgs
def drop_icon_imgs(text):
    """Remove decorative avatar/emoticon <img> tags (jira macro icons)."""
    lines = text.split("\n")
    masked = fence_lines(lines)

    def seg(s):
        def one(m):
            sm = re.search(r'src="([^"]*)"', m.group(0))
            return "" if sm and ICON_SRC.search(sm.group(1)) else m.group(0)
        return re.sub(r"(?<!\\)<img\b[^<>]*/?>", one, s)

    for i, l in enumerate(lines):
        if i in masked or "<img" not in l:
            continue
        lines[i] = sub_outside_code(l, seg)
    return "\n".join(lines)


def _scrub_open_tags(segment):
    """Whitelist-scrub attributes of raw-HTML opening tags in a text segment."""
    def sub(m):
        tag, attrs_s, selfc = m.group(1).lower(), m.group(2) or "", m.group(3)
        keep = KEEP_ATTRS.get(tag)
        if keep is None:                          # unknown tag -> not our HTML
            return m.group(0)
        attrs = dict(re.findall(r'([\w:-]+)="([^"]*)"', attrs_s))
        kept = "".join(f' {k}="{attrs[k]}"' for k in keep if k in attrs)
        return f"<{tag}{kept}{'/' if selfc else ''}>"
    return OPEN_TAG.sub(sub, segment)


def _anchor_to_md(inner, attrs_s, pipe_row, pagemap=None):
    """<a ...>inner</a> (tag-free inner) -> markdown, or None to keep HTML."""
    hm = re.search(r'href="([^"]*)"', attrs_s)
    if not hm:
        return None
    href = html.unescape(hm.group(1))
    text = re.sub(r"\s+", " ", html.unescape(inner)).replace("\xa0", " ").strip()
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
        hit = conf_page(href, pagemap)
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


def clean_anchors(text, pagemap=None, relname=""):
    """Flow anchors -> markdown; anchors in raw <table> blocks and anchors
    with nested tags -> attribute scrub only (confluence hrefs inside tables
    are rewritten to note-relative paths when the pagemap knows them).
    Raw-table element tags (td, p, ...) are attribute-scrubbed too.
    Fences/inline code stay untouched."""
    lines = text.split("\n")
    masked = fence_lines(lines)
    here = os.path.dirname(relname)
    depth = 0
    for i, l in enumerate(lines):
        if i in masked:
            continue
        in_tbl = depth > 0 or "<table" in l
        depth += len(re.findall(r"<table\b", l)) - l.count("</table>")
        if depth < 0:
            depth = 0
        if "<" not in l:
            continue
        pipe_row = bool(re.match(r"^[ \t]*\|", l))

        def seg(s):
            if not in_tbl:                        # flow: try full conversion
                def conv(m):
                    am = re.match(r"<a\b((?:\s[^<>]*?)?)>", m.group(0))
                    if not am:
                        return m.group(0)
                    md = _anchor_to_md(m.group(1), am.group(1), pipe_row, pagemap)
                    return md if md is not None else m.group(0)
                s = A_SIMPLE.sub(conv, s)
            elif pagemap:                         # in tables: localize hrefs
                def loc(m):
                    hit = conf_page(m.group(1), pagemap)
                    if not hit:
                        return m.group(0)
                    rel = os.path.relpath(hit[1], here) if here else hit[1]
                    return f'href="{urllib.parse.quote(rel)}"'
                s = re.sub(r'href="(https?://[^"]+)"', loc, s)
            if "<" in s:                          # leftovers: scrub attributes
                s = _scrub_open_tags(s)
            return s

        lines[i] = sub_outside_code(l, seg)
    return "\n".join(lines)


def conf_links_to_wikilinks(text, pagemap):
    """Flow markdown links/autolinks with absolute confluence URLs that
    resolve via the pagemap -> [[wikilinks]] (alias kept unless it is the
    URL itself or the page name)."""
    if not pagemap:
        return text
    lines = text.split("\n")
    masked = fence_lines(lines)
    for i, l in enumerate(lines):
        if i in masked or "http" not in l:
            continue
        pipe_row = bool(re.match(r"^[ \t]*\|", l))
        sep = "\\|" if pipe_row else "|"

        def seg(s):
            def sub_link(m):
                text_in, url = m.group(1).strip(), m.group(2)
                hit = conf_page(url, pagemap)
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
                       lambda m: f"[[{conf_page(m.group(1), pagemap)[0]}]]"
                       if conf_page(m.group(1), pagemap) else m.group(0), s)
            return s

        lines[i] = sub_outside_code(l, seg)
    return "\n".join(lines)


def _in_code_span(line, pos):
    for m in CODE_SPAN.finditer(line):
        if m.start() <= pos < m.end():
            return True
    return False


def repair_artifacts(text):
    """Pandoc artifact repairs, verified against source exports (see module
    docstring, item 7). Outside fences; inline code spans untouched."""
    lines = text.split("\n")
    masked = fence_lines(lines)
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

def mdlinks_to_wikilinks(text):
    """Relative [text](path.md) -> [[basename|text]] (corpus convention).
    Fresh convert.py output has none; they appear when an old-wiki table with
    internal links is converted (tablemd renders links as [text](href))."""
    lines = text.split("\n")
    masked = fence_lines(lines)
    for i, l in enumerate(lines):
        if i in masked or "](" not in l:
            continue
        pipe_row = bool(re.match(r"^[ \t]*\|", l))

        def seg(s):
            def sub(m):
                text_in, path = m.group(1), m.group(2)
                if path.startswith("/") or "]]" in text_in or "[[" in text_in:
                    return m.group(0)
                base = os.path.basename(urllib.parse.unquote(path))[:-3]
                plain = text_in.replace("\\|", "|").strip()   # human alias text
                if not plain or plain == base:
                    return f"[[{base}]]"
                if pipe_row:
                    return f"[[{base}\\|{plain.replace('|', chr(92) + '|')}]]"
                if "|" in plain:                  # would split [[target|alias]]
                    return m.group(0)
                return f"[[{base}|{plain}]]"
            return MD_LINK_MD.sub(sub, s)

        lines[i] = sub_outside_code(l, seg)
    return "\n".join(lines)


# ---------------------------------------------------------------- tables
def convert_tables(text, relname, log):
    """Replace raw <table> blocks with GFM tables (markers first, cleanup after)."""
    spans = fence_spans(text)
    # tables inside "> " blockquotes can't be block-parsed here -> log, keep as-is
    for m in re.finditer(r"(?m)^[ \t]*(?:>[ \t]*)+<table\b", text):
        if not any(a <= m.start() < b for a, b in spans):
            log.append((relname, "blockquote-table"))
    reps, pos = [], 0
    for m in re.finditer(r"(?m)^([ \t]*)<table\b", text):
        i = m.start()
        if i < pos or any(a <= i < b for a, b in spans):
            continue
        depth, j = 0, None
        for mm in re.finditer(r"<table\b|</table>", text[i:]):
            depth += 1 if not mm.group(0).startswith("</") else -1
            if depth == 0:
                j = i + mm.end()
                break
        if j is None:                             # unbalanced -> not a real block
            continue
        pos = j                                   # skip nested opens inside block
        try:
            el = lxml.html.fromstring(text[i:j])
            if el.tag != "table":
                el = el.find(".//table")
            if el is None:
                raise tablemd.Fallback("unparseable")
            gfm = tablemd.table_to_gfm(el, indent=m.group(1), unroll_pre=UNROLL,
                                       expand_spans=EXPAND)
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
        out.append(text[cur:i])
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


def process_file(path, relname, log, pagemap=None):
    old = open(path, encoding="utf-8").read()
    new = drop_icon_imgs(old)
    new = fix_empty_anchors_text(new)             # needs data-* attrs: before scrub
    new = clean_anchors(new, pagemap, relname)
    new, n_tbl = convert_tables(new, relname, log)
    new = mdlinks_to_wikilinks(new)
    new = conf_links_to_wikilinks(new, pagemap)
    new = repair_artifacts(new)
    return old, new, n_tbl


def main():
    global UNROLL, EXPAND
    flags = ("--dry-run", "--unroll-pre", "--expand-spans")
    args = [a for a in sys.argv[1:] if a not in flags]
    dry = "--dry-run" in sys.argv[1:]
    UNROLL = "--unroll-pre" in sys.argv[1:]
    EXPAND = "--expand-spans" in sys.argv[1:]
    if len(args) != 1:
        sys.exit("usage: fix_tables.py <dir-or-file> [--dry-run] [--unroll-pre] [--expand-spans]")
    root = args[0]
    files = []
    if os.path.isfile(root):
        files = [root]; base = os.path.dirname(root)
    else:
        base = root
        for dirpath, _, names in os.walk(root):
            files += [os.path.join(dirpath, n) for n in sorted(names) if n.endswith(".md")]
    pagemap = load_pagemap(base)
    if pagemap:
        print(f"[pagemap] {len(pagemap)} pages known -- confluence URLs will resolve")
    log, n_changed, n_tables = [], 0, 0
    n_wl_old = n_wl_new = 0                       # wikilink counters (sanity print)
    for f in sorted(files):
        rel = os.path.relpath(f, base)
        old, new, n_tbl = process_file(f, rel, log, pagemap)
        n_wl_old += len(re.findall(r"\[\[", old))
        n_wl_new += len(re.findall(r"\[\[", new))
        if new != old:
            n_changed += 1
            n_tables += n_tbl
            print(f"[fix] {rel}: {n_tbl} table(s) converted"
                  + (", anchors/cleanup" if n_tbl == 0 else ""))
            if not dry:
                open(f, "w", encoding="utf-8").write(new)
    for rel, reason in log:
        print(f"[fallback] {rel}: {reason}")
    print(f"[wikilinks] {n_wl_old} -> {n_wl_new}")
    print(f"[done] {n_changed}/{len(files)} files changed, {n_tables} tables converted, "
          f"{len(log)} fallbacks{' (dry-run)' if dry else ''}")


if __name__ == "__main__":
    main()
