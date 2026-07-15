#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tablemd v1 -- deterministic HTML <table> -> GFM pipe-table writer (lxml, no pandoc).

Shared by convert.py (v2) and fix_tables.py. Design rules:
- inline content (bold/italic/code/links/images) -> markdown; <br> and paragraph
  boundaries -> literal "<br>" inside the cell; "|" escaped as "\\|";
- lists in cells -> "<br>"-joined lines with "•" marker (ol: "N."), nesting via
  "&nbsp;&nbsp;" per level (accepted layout loss, never data loss);
- header: <thead> row or a first all-<th> row; otherwise a synthetic EMPTY header
  row (data rows are never promoted to header);
- <pre>/multi-line <code> in cells: 1 line -> inline code; 2..5 lines without
  indentation -> per-line inline code joined by "<br>"; else Fallback("multiline-pre");
- optional unroll mode (table_to_gfm(..., unroll_pre=True)): instead of the
  multiline-pre Fallback the cell gets "см. Пример N ниже" and the <pre> bodies
  are emitted AFTER the table as "**<column header|строка R> — Пример N:**" +
  fenced code block (language from pre/code class, else sniffed: {/[ -> json,
  < -> xml); pre content is kept byte-exact (edge newlines trimmed);
- Fallback (exception, caller keeps raw HTML and logs): colspan/rowspan > 1,
  nested tables, long/indented pre, empty table;
- optional expand mode (table_to_gfm(..., expand_spans=True)): colspan/rowspan
  no longer raise -- the grid is expanded: rowspan repeats the value on every
  spanned row, colspan puts the value in the first column of the span and pads
  the rest with "" (layout loss, never data loss);
- empty attachment anchors (<a ...></a>): text from data-linked-resource-default-alias,
  else aria-label, else basename(href) -- fill_empty_anchors()/anchor_fallback_text().
"""
import os, re, html
import urllib.parse
from lxml import etree


class Fallback(Exception):
    """Raised when a lossless GFM conversion is impossible; caller keeps raw HTML."""
    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


# ---------------------------------------------------------------- escaping
_MD_ESC = re.compile(r"([\\`*_\[\]<|])")

def esc_text(s):
    """Plain text node -> markdown-safe inline text (whitespace collapsed)."""
    s = s.replace("\xa0", " ")
    s = re.sub(r"\s+", " ", s)
    s = _MD_ESC.sub(r"\\\1", s)
    s = re.sub(r"&(?=#|\w+;)", r"\\&", s)      # only entity-lookalikes need escaping
    s = s.replace("~~", "\\~\\~")
    return s

def code_span(s):
    """Inline code span; pipes escaped (GFM tables honor \\| even inside code)."""
    s = s.replace("\xa0", " ")
    if not s.strip():
        return ""
    runs = re.findall(r"`+", s)
    fence = "`" * (max((len(r) for r in runs), default=0) + 1)
    pad = " " if (s.startswith("`") or s.endswith("`")) else ""
    return fence + pad + s.replace("|", "\\|") + pad + fence

def esc_url(u):
    for ch, enc in (("|", "%7C"), (" ", "%20"), ("(", "%28"), (")", "%29"),
                    ("<", "%3C"), (">", "%3E")):
        u = u.replace(ch, enc)
    return u


# ---------------------------------------------------------------- empty anchors
def anchor_fallback_text(a):
    """Human text for a text-less attachment link (Confluence file-card)."""
    for attr in ("data-linked-resource-default-alias", "aria-label"):
        v = (a.get(attr) or "").strip()
        if v:
            return v
    href = (a.get("href") or "").split("?")[0].split("#")[0]
    return os.path.basename(urllib.parse.unquote(href))

def fill_empty_anchors(root):
    """Give text to every <a href> with no visible content. Returns count fixed."""
    n = 0
    for a in root.iter("a"):
        if not a.get("href"):
            continue
        if "".join(a.itertext()).strip() or a.xpath(".//img"):
            continue
        txt = anchor_fallback_text(a)
        if txt:
            a.text = txt
            n += 1
    return n


# ---------------------------------------------------------------- inline renderer
_WRAP = {"strong": "**", "b": "**", "em": "*", "i": "*", "del": "~~", "s": "~~",
         "strike": "~~"}
_BLOCK = {"p", "div", "ul", "ol", "pre", "blockquote", "h1", "h2", "h3", "h4",
          "h5", "h6", "table"}

def _pre_text(el):
    """Text of a <pre>/<code> with <br> as newline (document order)."""
    parts = [el.text or ""]
    for d in el.iterdescendants():
        if d.tag == "br":
            parts.append("\n")
        else:
            parts.append(d.text or "")
        parts.append(d.tail or "")
    return "".join(parts)

_unroll = None          # None -> disabled; list -> collect unrolled examples
                        # (set per-table by table_to_gfm(unroll_pre=True))

def _pre_lang(el):
    """Fence language: pre/code class attr, else deterministic content sniff."""
    cands = [el]
    if el.tag == "pre":
        cands += [c for c in el if c.tag == "code"]
    for cand in cands:
        tok = ((cand.get("class") or "").split() or [""])[0]
        tok = tok[9:] if tok.startswith("language-") else tok
        if re.fullmatch(r"[A-Za-z0-9+#.-]{1,20}", tok) and "pre" not in tok.lower():
            return tok.lower()
    head = _pre_text(el).lstrip()[:1]
    return {"{": "json", "[": "json", "<": "xml"}.get(head, "")

def _code_block(el):
    """<pre> (or multi-line <code>) per policy; may raise Fallback."""
    txt = _pre_text(el).strip("\n")
    lines = txt.split("\n")
    if len(lines) == 1:
        return code_span(lines[0])
    # short snippet without meaningful indentation -> per-line inline code
    if len(lines) <= 5 and not any(l[:1] in (" ", "\t") for l in lines):
        return "<br>".join(code_span(l) for l in lines)
    if _unroll is None:
        raise Fallback("multiline-pre")
    n = len(_unroll) + 1
    _unroll.append({"n": n, "lang": _pre_lang(el), "text": txt,
                    "row": 0, "col": 0})
    return f"см. Пример {n} ниже"

def _render_inline(el):
    tag = el.tag
    if not isinstance(tag, str):                 # comment / PI
        return ""
    if tag == "br":
        return "<br>"
    if tag == "img":
        alt = esc_text(el.get("alt") or "")
        src = el.get("src") or ""
        return f"![{alt}]({esc_url(src)})" if src else ""
    if tag == "a":
        return _render_link(el)
    if tag == "code":
        txt = _pre_text(el)
        if "\n" in txt.strip("\n"):
            return _code_block(el)
        return code_span(txt.strip("\n"))
    if tag == "pre":
        return _code_block(el)
    if tag == "table":
        raise Fallback("nested-table")
    if tag in _WRAP:
        inner = _render_children(el).strip()
        if not inner or re.fullmatch(r"(?:<br>|\s)+", inner):   # <strong><br/></strong>
            return inner
        return f"{_WRAP[tag]}{inner}{_WRAP[tag]}"
    if tag in ("ul", "ol"):
        return _render_list(el, 0)
    # h1..h6 inside a cell -> bold line
    if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
        inner = _render_children(el).strip()
        return f"**{inner}**" if inner else ""
    # p / div / blockquote / span / font / anything else -> transparent
    return _render_children(el)

def _render_children(el):
    parts = []
    if el.text:
        parts.append(esc_text(el.text))
    for c in el:
        parts.append(_render_inline(c))
        if isinstance(c.tag, str) and c.tag in _BLOCK:
            parts.append("<br>")
        if c.tail:
            parts.append(esc_text(c.tail))
    return "".join(parts)

def _render_link(a):
    if not "".join(a.itertext()).strip() and not a.xpath(".//img"):
        text = esc_text(anchor_fallback_text(a))
    else:
        text = _render_children(a).strip()
    href = a.get("href") or ""
    if not href:
        return text
    return f"[{text}]({esc_url(href)})" if text else f"<{esc_url(href)}>"

def _render_list(lst, depth):
    lines = []
    n = 0
    for li in lst:
        if li.tag != "li":
            continue
        n += 1
        marker = "•" if lst.tag == "ul" else f"{n}."
        # nested lists render as extra lines; the rest of <li> is inline
        nested = []
        clone_parts = []
        if li.text:
            clone_parts.append(esc_text(li.text))
        for c in li:
            if isinstance(c.tag, str) and c.tag in ("ul", "ol"):
                nested.append(_render_list(c, depth + 1))
            else:
                clone_parts.append(_render_inline(c))
                if isinstance(c.tag, str) and c.tag in _BLOCK:
                    clone_parts.append("<br>")
            if c.tail:
                clone_parts.append(esc_text(c.tail))
        head = re.sub(r"(?:<br>\s*)+$", "", "".join(clone_parts).strip())
        lines.append("&nbsp;&nbsp;" * depth + f"{marker} {head}".rstrip())
        lines.extend(x for x in nested if x)
    return "<br>".join(lines)


# ---------------------------------------------------------------- cell -> md
def cell_md(cell):
    """Render one <td>/<th> to a single-line markdown string. May raise Fallback."""
    blocks = []
    cur = []

    def flush():
        s = "".join(cur).strip()
        cur.clear()
        if s and s != "<br>":
            blocks.append(s)

    if cell.text and cell.text.strip():
        cur.append(esc_text(cell.text))
    for c in cell:
        if isinstance(c.tag, str) and c.tag in _BLOCK:
            flush()
            b = _render_inline(c).strip()
            if b and b != "<br>":
                blocks.append(b)
        else:
            cur.append(_render_inline(c))
        if c.tail:
            cur.append(esc_text(c.tail))    # keep single spaces between inlines
    flush()
    s = "<br>".join(blocks)
    s = re.sub(r"(?:<br>[ ]*){2,}", "<br>", s)               # collapse br runs
    s = re.sub(r"^(?:<br>[ ]*)+|(?:[ ]*<br>)+$", "", s).strip()
    return s


# ---------------------------------------------------------------- table -> GFM
def _span(cell, attr):
    v = (cell.get(attr) or "").strip()
    return int(v) if v.isdigit() and int(v) > 1 else 1


def table_to_gfm(table, indent="", unroll_pre=False, expand_spans=False):
    """lxml <table> element -> GFM pipe table (string). Raises Fallback when a
    lossless conversion is impossible (caller keeps the raw HTML and logs).
    unroll_pre=True: multiline-pre cells no longer raise -- each becomes
    "см. Пример N ниже" and the code bodies are appended after the table as
    bold-labelled fenced blocks (see module docstring).
    expand_spans=True: colspan/rowspan cells no longer raise -- rowspan repeats
    the value on every spanned row, colspan pads the span with "" cells."""
    global _unroll
    if table.xpath(".//table"):
        raise Fallback("nested-table")
    if not expand_spans:
        for c in table.xpath(".//td | .//th"):
            for attr in ("colspan", "rowspan"):
                v = (c.get(attr) or "").strip()
                if v and v != "1":
                    raise Fallback("colspan-rowspan")
    _unroll = [] if unroll_pre else None
    try:
        rows = []                                # (cells:list[str], all_th, in_thead)
        pending = {}     # col -> [rows_left, text]: open rowspans (expand_spans)
        for tr in table.iter("tr"):
            cells = [c for c in tr if c.tag in ("td", "th")]
            if not cells and not pending:
                continue
            row_cells, col, queue = [], 0, list(cells)
            while queue or (pending and col <= max(pending)):
                if col in pending:               # cell continued from a rowspan
                    rem = pending[col]
                    row_cells.append(rem[1])
                    rem[0] -= 1
                    if rem[0] <= 0:
                        del pending[col]
                    col += 1
                    continue
                if not queue:                    # gap before a trailing rowspan
                    row_cells.append("")
                    col += 1
                    continue
                c = queue.pop(0)
                k = len(_unroll) if _unroll is not None else 0
                txt = cell_md(c)
                if _unroll is not None:          # bind fresh examples to a cell
                    for e in _unroll[k:]:
                        e["row"], e["col"] = len(rows), col
                cs, rs = _span(c, "colspan"), _span(c, "rowspan")
                for i in range(cs):              # value in first col of the span
                    row_cells.append(txt if i == 0 else "")
                    if rs > 1:
                        pending[col + i] = [rs - 1, txt if i == 0 else ""]
                col += cs
            if not row_cells:
                continue
            rows.append((row_cells, bool(cells) and all(c.tag == "th" for c in cells),
                         bool(tr.xpath("ancestor::thead"))))
        if not rows:
            raise Fallback("empty-table")
        ncol = max(len(r[0]) for r in rows)
        has_header = rows[0][1] or rows[0][2]
        if has_header:                           # real header row
            header, body = rows[0][0], rows[1:]
        else:                                    # never promote data to header
            header, body = [""] * ncol, rows
        def fmt(cells):
            cells = cells + [""] * (ncol - len(cells))
            return indent + "| " + " | ".join(cells) + " |"
        out = [fmt(header), indent + "|" + "----|" * ncol]
        out.extend(fmt(r[0]) for r in body)
        gfm = "\n".join(out)
        for e in (_unroll or []):
            gfm += "\n\n" + "\n".join(indent + l for l in _example_md(e, header, has_header).split("\n"))
        return gfm
    finally:
        _unroll = None

def _example_md(e, header, has_header):
    """One unrolled example: '**<label> — Пример N:**' + fenced code block."""
    label = ""
    if has_header and e["row"] != 0 and e["col"] < len(header):
        label = re.sub(r"[*`]", "", header[e["col"]]).replace("\\", "").strip()
    if not label:
        label = f"строка {e['row'] if has_header else e['row'] + 1}"
    runs = re.findall(r"`+", e["text"])
    f = "`" * max(3, max((len(r) for r in runs), default=0) + 1)
    return f"**{label} — Пример {e['n']}:**\n\n{f}{e['lang']}\n{e['text']}\n{f}"
