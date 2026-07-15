#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fix_tables v1 -- postprocessor for ALREADY converted .md pages (no source HTML).

Does exactly two things, everything else stays byte-for-byte:
1. raw Confluence HTML <table> blocks (line starts with optional indent +
   "<table", ends at the balanced "</table>") -> GFM pipe tables via tablemd;
   fallback (kept as raw HTML, logged): colspan/rowspan, nested tables,
   long/indented <pre> in cells. Junk lines adjacent to a REPLACED block
   (blank runs, lone "\\" from <br/>) are collapsed to one blank line.
2. empty attachment anchors <a ...></a> get visible text:
   data-linked-resource-default-alias -> aria-label -> basename(href)
   (applied inside tables and standalone; code fences are never touched).

Idempotent: a second run changes 0 files.
CLI: python3 fix_tables.py <dir-or-file> [--dry-run] [--unroll-pre]
--unroll-pre: multiline-pre таблицы не остаются HTML, а разворачиваются —
ячейка получает «см. Пример N ниже», код выносится фенсами после таблицы.
"""
import os, re, sys, html
import lxml.html
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tablemd

UNROLL = False   # --unroll-pre: см. docstring

S_MARK, E_MARK = "\x00TBL\x00", "\x00/TBL\x00"


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
            gfm = tablemd.table_to_gfm(el, indent=m.group(1), unroll_pre=UNROLL)
        except tablemd.Fallback as fb:
            log.append((relname, fb.reason))
            continue
        reps.append((i, j, gfm))
    if not reps:
        return text, 0
    out, cur = [], 0
    for i, j, gfm in reps:
        out.append(text[cur:i])
        out.append(S_MARK + "\n" + gfm + "\n" + E_MARK)
        cur = j
    out.append(text[cur:])
    return _cleanup_markers("".join(out)), len(reps)


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


def process_file(path, relname, log):
    old = open(path, encoding="utf-8").read()
    new = fix_empty_anchors_text(old)
    new, n_tbl = convert_tables(new, relname, log)
    return old, new, n_tbl


def main():
    global UNROLL
    flags = ("--dry-run", "--unroll-pre")
    args = [a for a in sys.argv[1:] if a not in flags]
    dry = "--dry-run" in sys.argv[1:]
    UNROLL = "--unroll-pre" in sys.argv[1:]
    if len(args) != 1:
        sys.exit("usage: fix_tables.py <dir-or-file> [--dry-run] [--unroll-pre]")
    root = args[0]
    files = []
    if os.path.isfile(root):
        files = [root]; base = os.path.dirname(root)
    else:
        base = root
        for dirpath, _, names in os.walk(root):
            files += [os.path.join(dirpath, n) for n in sorted(names) if n.endswith(".md")]
    log, n_changed, n_tables = [], 0, 0
    for f in sorted(files):
        rel = os.path.relpath(f, base)
        old, new, n_tbl = process_file(f, rel, log)
        if new != old:
            n_changed += 1
            n_tables += n_tbl
            print(f"[fix] {rel}: {n_tbl} table(s) converted"
                  + (", anchors/cleanup" if n_tbl == 0 else ""))
            if not dry:
                open(f, "w", encoding="utf-8").write(new)
    for rel, reason in log:
        print(f"[fallback] {rel}: {reason}")
    print(f"[done] {n_changed}/{len(files)} files changed, {n_tables} tables converted, "
          f"{len(log)} fallbacks{' (dry-run)' if dry else ''}")


if __name__ == "__main__":
    main()
