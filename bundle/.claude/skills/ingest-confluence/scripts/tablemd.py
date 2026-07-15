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
- Fallback (exception, caller keeps raw HTML and logs): colspan/rowspan > 1,
  nested tables, long/indented pre, empty table;
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

def _code_block(el):
    """<pre> (or multi-line <code>) per policy; may raise Fallback."""
    txt = _pre_text(el).strip("\n")
    lines = txt.split("\n")
    if len(lines) == 1:
        return code_span(lines[0])
    # short snippet without meaningful indentation -> per-line inline code
    if len(lines) <= 5 and not any(l[:1] in (" ", "\t") for l in lines):
        return "<br>".join(code_span(l) for l in lines)
    raise Fallback("multiline-pre")

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
def table_to_gfm(table, indent=""):
    """lxml <table> element -> GFM pipe table (string). Raises Fallback when a
    lossless conversion is impossible (caller keeps the raw HTML and logs)."""
    if table.xpath(".//table"):
        raise Fallback("nested-table")
    for c in table.xpath(".//td | .//th"):
        for attr in ("colspan", "rowspan"):
            v = (c.get(attr) or "").strip()
            if v and v != "1":
                raise Fallback("colspan-rowspan")
    rows = []                                    # (cells:list[str], all_th, in_thead)
    for tr in table.iter("tr"):
        cells = [c for c in tr if c.tag in ("td", "th")]
        if not cells:
            continue
        rows.append(([cell_md(c) for c in cells],
                     all(c.tag == "th" for c in cells),
                     bool(tr.xpath("ancestor::thead"))))
    if not rows:
        raise Fallback("empty-table")
    ncol = max(len(r[0]) for r in rows)
    if rows[0][1] or rows[0][2]:                 # real header row
        header, body = rows[0][0], rows[1:]
    else:                                        # never promote data to header
        header, body = [""] * ncol, rows
    def fmt(cells):
        cells = cells + [""] * (ncol - len(cells))
        return indent + "| " + " | ".join(cells) + " |"
    out = [fmt(header), indent + "|" + "----|" * ncol]
    out.extend(fmt(r[0]) for r in body)
    return "\n".join(out)
