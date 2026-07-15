#!/usr/bin/env python3
"""Экспорт md-документа в PDF для сдачи за пределы корпуса.

Детерминированный конвертер (правило границы): [[wikilinks]] → текст,
![[embeds]] → встроенные изображения, frontmatter → заголовок; pandoc
собирает standalone-HTML, PDF печёт первый доступный движок:
typst → weasyprint → wkhtmltopdf → Chrome headless → (fallback) .html.

Usage: export_pdf.py <doc.md> [-o out.pdf] [--corpus DIR ...]
                     [--engine auto|typst|weasyprint|wkhtmltopdf|chrome|html]
Exit: 0 — PDF собран; 3 — движка нет, оставлен .html; 2 — ошибка.
"""
import argparse, os, re, shutil, subprocess, sys, tempfile, unicodedata

WIKILINK = re.compile(r"(!?)\[\[([^\]\|#\\]+)(?:#[^\]\|\\]*)?(?:\\?\|([^\]]*))?\]\]")
FENCE = re.compile(r"^\s*(```|~~~)")
IMG_EXT = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp"}

CSS = """
@page { size: A4; margin: 22mm 18mm; }
body { font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
       font-size: 11pt; line-height: 1.45; color: #1c1e21; max-width: 46em; margin: auto; }
h1, h2, h3 { line-height: 1.25; }
table { border-collapse: collapse; width: 100%; font-size: 10pt; }
th, td { border: 1px solid #b8bcc2; padding: 4px 8px; text-align: left; vertical-align: top; }
th { background: #eef0f3; }
code { font-family: Menlo, Consolas, monospace; font-size: 9.5pt;
       background: #f1f2f4; padding: 1px 4px; border-radius: 3px; }
pre { background: #f1f2f4; padding: 10px; border-radius: 4px; overflow-x: auto; }
pre code { background: none; padding: 0; }
img { max-width: 100%; }
blockquote { border-left: 3px solid #c8ccd2; margin-left: 0; padding-left: 12px; color: #4a4e55; }
"""


def key(name):
    return unicodedata.normalize("NFC", name).casefold()


def build_index(corpus_dirs):
    idx = {}
    for root in corpus_dirs:
        if not os.path.isdir(root):
            continue
        for dirpath, _dirs, files in os.walk(root):
            for f in files:
                idx.setdefault(key(f), os.path.join(dirpath, f))
                base, ext = os.path.splitext(f)
                if ext.lower() == ".md":
                    idx.setdefault(key(base), os.path.join(dirpath, f))
    return idx


def resolve_wikilinks(md, idx):
    out, in_fence = [], False
    for line in md.splitlines(keepends=True):
        if FENCE.match(line):
            in_fence = not in_fence
            out.append(line); continue
        if in_fence:
            out.append(line); continue

        def sub(m):
            bang, target, alias = m.group(1), m.group(2).strip(), m.group(3)
            text = (alias or target).strip()
            hit = idx.get(key(target)) or idx.get(key(os.path.basename(target)))
            if bang and hit and os.path.splitext(hit)[1].lower() in IMG_EXT:
                return "![%s](%s)" % (text, os.path.abspath(hit))
            # ссылки внутрь корпуса в PDF не ведут никуда — остаётся текст
            return text
        out.append(WIKILINK.sub(sub, line))
    return "".join(out)


def strip_frontmatter(md):
    if md.startswith("---\n"):
        end = md.find("\n---", 4)
        if end != -1:
            fm = md[4:end]
            body = md[end + 4:].lstrip("\n")
            m = re.search(r'^title:\s*"?([^"\n]+)"?\s*$', fm, re.M)
            return body, (m.group(1).strip() if m else None)
    return md, None


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("doc")
    ap.add_argument("-o", "--out")
    ap.add_argument("--corpus", nargs="*", default=None)
    ap.add_argument("--engine", default="auto")
    a = ap.parse_args()

    doc = os.path.abspath(a.doc)
    if not os.path.isfile(doc):
        print("export_pdf: нет файла: %s" % a.doc); return 2
    out_pdf = os.path.abspath(a.out) if a.out else os.path.splitext(doc)[0] + ".pdf"
    docdir = os.path.dirname(doc)
    corpus = a.corpus if a.corpus is not None else \
        [docdir] + [os.path.join(os.path.dirname(docdir), d) for d in ("wiki", "spec", "assets")]

    with open(doc, encoding="utf-8") as fh:
        md = fh.read()
    body, title = strip_frontmatter(md)
    body = resolve_wikilinks(body, build_index(corpus))
    title = title or os.path.splitext(os.path.basename(doc))[0]

    tmp = tempfile.mkdtemp(prefix="loftpdf-")
    try:
        mdfile = os.path.join(tmp, "doc.md")
        cssfile = os.path.join(tmp, "doc.css")
        html = os.path.join(tmp, "doc.html")
        with open(mdfile, "w", encoding="utf-8") as fh:
            fh.write(body)
        with open(cssfile, "w", encoding="utf-8") as fh:
            fh.write(CSS)

        want = a.engine
        if want in ("auto", "typst") and shutil.which("typst"):
            r = run(["pandoc", mdfile, "-o", out_pdf, "--pdf-engine=typst",
                     "--metadata", "title=" + title, "--resource-path", docdir])
            if r.returncode == 0:
                print("export_pdf: %s (typst)" % out_pdf); return 0
            if want == "typst":
                print(r.stderr); return 2

        r = run(["pandoc", mdfile, "-s", "-o", html, "--css", cssfile,
                 "--metadata", "title=" + title, "--embed-resources",
                 "--resource-path", docdir])
        if r.returncode != 0:
            print("export_pdf: pandoc: %s" % r.stderr.strip()); return 2

        engines = []
        if shutil.which("weasyprint"):
            engines.append(("weasyprint", ["weasyprint", html, out_pdf]))
        if shutil.which("wkhtmltopdf"):
            engines.append(("wkhtmltopdf", ["wkhtmltopdf", "-q", html, out_pdf]))
        chrome = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
        for c in (shutil.which("chromium"), shutil.which("google-chrome"),
                  chrome if os.path.exists(chrome) else None):
            if c:
                engines.append(("chrome", [c, "--headless", "--disable-gpu",
                                           "--no-pdf-header-footer",
                                           "--print-to-pdf=" + out_pdf,
                                           "file://" + html]))
                break
        if want != "auto":
            engines = [e for e in engines if e[0] == want]

        for name, cmd in engines:
            r = run(cmd)
            if r.returncode == 0 and os.path.isfile(out_pdf) and os.path.getsize(out_pdf) > 0:
                print("export_pdf: %s (%s)" % (out_pdf, name)); return 0

        keep = os.path.splitext(out_pdf)[0] + ".html"
        shutil.copy(html, keep)
        print("export_pdf: PDF-движка нет — оставлен %s; напечатай в PDF из браузера (⌘P)\n"
              "  рекомендуемый движок: brew install typst" % keep)
        return 3
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
