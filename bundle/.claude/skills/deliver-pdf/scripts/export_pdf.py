#!/usr/bin/env python3
"""Экспорт md-документа в PDF для сдачи за пределы корпуса.

Детерминированный конвертер (правило границы): [[wikilinks]] → текст,
![[embeds]] → встроенные изображения, frontmatter → заголовок; pandoc
собирает standalone-HTML, PDF печёт первый доступный движок:
typst → weasyprint → wkhtmltopdf → Chrome headless → (fallback) .html.

Usage: export_pdf.py <doc.md> [-o out.pdf] [--corpus DIR ...] [--strict]
                     [--engine auto|typst|weasyprint|wkhtmltopdf|chrome|html]
       export_pdf.py --md out.md <doc.md>            # markdown без pandoc
       export_pdf.py --bundle пакет.md <док1.md> <док2.md> ...

Корпус по умолчанию — wiki/ spec/ assets/ от корня проекта (ближайший
каталог вверх от документа, где есть wiki/ или spec/) плюс каталог самого
документа; --corpus переопределяет.

Exit: 0 — собрано; 1 — --strict и есть неразрешённые ссылки;
      2 — ошибка (нет файла, нет pandoc, движок не собрал PDF);
      3 — PDF-движка в системе нет, оставлен .html.

LOFT_CHROME — тест-ручка: путь к бинарю вместо найденного Chrome.
LOFT_ENGINE_TIMEOUT — тест-ручка: секунд на попытку движка (по умолчанию 180).
"""
import argparse, os, re, shutil, subprocess, sys, tempfile, time, unicodedata

WIKILINK = re.compile(r"(!?)\[\[([^\]\|#\\]+)(?:#[^\]\|\\]*)?(?:\\?\|([^\]]*))?\]\]")
FENCE = re.compile(r"^\s*(```|~~~)")
H1 = re.compile(r"^#[ \t]+\S")
IMG_EXT = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp"}
ENGINES = ("auto", "typst", "weasyprint", "wkhtmltopdf", "chrome", "html")
TIMEOUT = 180

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


def warn(msg):
    print(msg, file=sys.stderr)


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


def project_root(docdir):
    """Ближайший каталог вверх от документа, где лежит wiki/ или spec/."""
    d = os.path.abspath(docdir)
    while True:
        if os.path.isdir(os.path.join(d, "wiki")) or os.path.isdir(os.path.join(d, "spec")):
            return d
        up = os.path.dirname(d)
        if up == d:
            return None
        d = up


def default_corpus(docdir):
    root = project_root(docdir) or os.path.dirname(os.path.abspath(docdir))
    dirs, seen = [], set()
    for d in [docdir] + [os.path.join(root, x) for x in ("wiki", "spec", "assets")]:
        d = os.path.abspath(d)
        if d not in seen:
            seen.add(d); dirs.append(d)
    return dirs


def resolve_wikilinks(md, idx, unresolved=None, relative_to=None, label=""):
    """[[ссылка]] → текст, ![[картинка]] → md-картинка. Неразрешённое —
    в unresolved: молча терять содержимое сдаваемого документа нельзя."""
    out, in_fence = [], False

    def note(what):
        if unresolved is not None and (label + what) not in unresolved:
            unresolved.append(label + what)

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
            if not hit:
                note(target)
            elif bang:
                if os.path.splitext(hit)[1].lower() in IMG_EXT:
                    path = os.path.relpath(hit, relative_to) if relative_to else os.path.abspath(hit)
                    return "![%s](%s)" % (text, path)
                note("%s (не изображение)" % target)
            # ссылки внутрь корпуса в PDF не ведут никуда — остаётся текст
            return text
        out.append(WIKILINK.sub(sub, line))
    return "".join(out)


def unquote(v):
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        inner = v[1:-1]
        if v[0] == '"':
            return re.sub(r"\\(.)", r"\1", inner)
        return inner.replace("''", "'")
    return v


def strip_frontmatter(md):
    """Терпимый разбор паспорта: CRLF, обе кавычки, экранированная кавычка."""
    lines = md.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return md, None
    for i in range(1, len(lines)):
        if lines[i].strip() in ("---", "..."):
            fm = "".join(lines[1:i])
            body = "".join(lines[i + 1:]).lstrip("\r\n")
            m = re.search(r"^title:[ \t]*(.*?)[ \t\r]*$", fm, re.M)
            title = unquote(m.group(1).strip()).strip() if m else None
            return body, (title or None)
    return md, None


def starts_with_h1(body):
    for line in body.splitlines():
        if line.strip():
            return bool(H1.match(line))
    return False


def read_doc(path):
    with open(path, encoding="utf-8") as fh:
        return strip_frontmatter(fh.read())


def engine_timeout():
    """Секунд на попытку движка; LOFT_ENGINE_TIMEOUT — тест-ручка."""
    try:
        t = float(os.environ.get("LOFT_ENGINE_TIMEOUT", ""))
    except ValueError:
        return TIMEOUT
    return t if t > 0 else TIMEOUT


def run(cmd):
    """Ни один движок не висит дольше таймаута: сдача не уходит в никуда."""
    limit = engine_timeout()
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=limit)
        return r.returncode, (r.stderr or "").strip()
    except subprocess.TimeoutExpired:
        return 124, "не ответил за %g с" % limit
    except OSError as e:
        return 127, str(e)


def written(path, since):
    """Файл есть, непустой и записан этим прогоном, а не остался с прошлого."""
    try:
        st = os.stat(path)
    except OSError:
        return False
    return st.st_size > 0 and st.st_mtime >= since - 2


def ensure_parent(path):
    d = os.path.dirname(path) or "."
    if os.path.isdir(d):
        return None
    try:
        os.makedirs(d)
    except OSError as e:
        return "не удалось создать каталог %s: %s" % (d, e)
    return None


def deliver(src, dst):
    """Готовый PDF въезжает на место старого одним движением."""
    try:
        if os.path.exists(dst):
            os.remove(dst)
        shutil.move(src, dst)
    except OSError as e:
        return "не удалось записать %s: %s" % (dst, e)
    return None


def report_unresolved(unresolved, strict):
    if not unresolved:
        return 0
    warn("export_pdf: не разрешено: %d (%s)" % (len(unresolved), ", ".join(unresolved)))
    if strict:
        warn("export_pdf: --strict — сдача остановлена")
        return 1
    return 0


def build_markdown(docs, out_md, corpus_arg, strict):
    """Пакет для читателей-ИИ: чистый markdown, каждый документ под своим H1."""
    err = ensure_parent(out_md)
    if err:
        warn("export_pdf: " + err); return 2
    parts, unresolved, cache = [], [], {}
    outdir = os.path.dirname(out_md) or "."
    for doc in docs:
        body, title = read_doc(doc)
        corpus = corpus_arg if corpus_arg is not None else default_corpus(os.path.dirname(doc))
        ck = tuple(corpus)
        if ck not in cache:
            cache[ck] = build_index(corpus)
        label = "%s: " % os.path.basename(doc) if len(docs) > 1 else ""
        body = resolve_wikilinks(body, cache[ck], unresolved, relative_to=outdir, label=label)
        if not starts_with_h1(body):
            head = title or os.path.splitext(os.path.basename(doc))[0]
            body = "# %s\n\n%s" % (head, body.lstrip("\n"))
        parts.append(body.strip() + "\n")
    rc = report_unresolved(unresolved, strict)
    if rc:
        return rc
    with open(out_md, "w", encoding="utf-8") as fh:
        fh.write("\n\n".join(parts))
    print("export_pdf: %s (%d док.)" % (out_md, len(docs)))
    return 0


def chrome_binary():
    env = os.environ.get("LOFT_CHROME")
    if env:
        return env if os.path.exists(env) else None
    mac = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    for c in (shutil.which("chromium"), shutil.which("google-chrome"),
              mac if os.path.exists(mac) else None):
        if c:
            return c
    return None


def build_pdf(doc, out_pdf, corpus_arg, want, strict):
    err = ensure_parent(out_pdf)
    if err:
        warn("export_pdf: " + err); return 2

    body, title = read_doc(doc)
    corpus = corpus_arg if corpus_arg is not None else default_corpus(os.path.dirname(doc))
    unresolved = []
    body = resolve_wikilinks(body, build_index(corpus), unresolved)
    rc = report_unresolved(unresolved, strict)
    if rc:
        return rc
    title = title or os.path.splitext(os.path.basename(doc))[0]
    # свой H1 в теле — заголовок из паспорта в текст не идёт, иначе он двоится
    own_h1 = starts_with_h1(body)
    docdir = os.path.dirname(doc)

    if not shutil.which("pandoc"):
        warn("export_pdf: нет pandoc — ставится `brew install pandoc`"); return 2

    tmp = tempfile.mkdtemp(prefix="loftpdf-")
    try:
        mdfile = os.path.join(tmp, "doc.md")
        cssfile = os.path.join(tmp, "doc.css")
        html = os.path.join(tmp, "doc.html")
        newpdf = os.path.join(tmp, "out.pdf")
        with open(mdfile, "w", encoding="utf-8") as fh:
            fh.write(body)
        with open(cssfile, "w", encoding="utf-8") as fh:
            fh.write(CSS)

        failed, typst_tried = [], False
        if want in ("auto", "typst") and shutil.which("typst"):
            typst_tried = True
            cmd = ["pandoc", mdfile, "-o", newpdf, "--pdf-engine=typst",
                   "--resource-path", docdir]
            if not own_h1:
                cmd += ["--metadata", "title=" + title]
            since = time.time()
            code, err = run(cmd)
            if code == 0 and written(newpdf, since):
                err = deliver(newpdf, out_pdf)
                if err:
                    warn("export_pdf: " + err); return 2
                print("export_pdf: %s (typst)" % out_pdf); return 0
            # Провал первого движка цепочки идёт в общий отчёт вместе с
            # остальными: иначе конец объявляет, что PDF-движка нет, и советует
            # поставить typst, который стоит и только что упал.
            failed.append("  - typst: %s" % (err or "вернул 0, но PDF не записан"))

        cmd = ["pandoc", mdfile, "-s", "-o", html, "--css", cssfile,
               "--metadata", ("pagetitle=" if own_h1 else "title=") + title,
               "--embed-resources", "--resource-path", docdir]
        code, err = run(cmd)
        if code != 0:
            warn("export_pdf: pandoc: %s" % (err or "код %d" % code)); return 2

        engines = []
        if shutil.which("weasyprint"):
            engines.append(("weasyprint", ["weasyprint", html, newpdf]))
        if shutil.which("wkhtmltopdf"):
            engines.append(("wkhtmltopdf", ["wkhtmltopdf", "-q", html, newpdf]))
        chrome = chrome_binary()
        if chrome:
            engines.append(("chrome", [chrome, "--headless", "--disable-gpu",
                                       "--no-pdf-header-footer",
                                       "--print-to-pdf=" + newpdf,
                                       "file://" + html]))
        keep = os.path.splitext(out_pdf)[0] + ".html"
        if want == "html":
            shutil.copy(html, keep)
            print("export_pdf: %s (standalone-HTML)" % keep); return 0
        if want != "auto":
            have = [n for n, _ in engines]
            engines = [e for e in engines if e[0] == want]
            if not engines and not typst_tried:
                warn("export_pdf: движок %s недоступен; в системе есть: %s"
                     % (want, ", ".join(have) or "ни одного")); return 2

        for name, cmd in engines:
            since = time.time()
            code, err = run(cmd)
            if code == 0 and written(newpdf, since):
                err = deliver(newpdf, out_pdf)
                if err:
                    warn("export_pdf: " + err); return 2
                print("export_pdf: %s (%s)" % (out_pdf, name)); return 0
            failed.append("  - %s: %s" % (name, err or "вернул 0, но PDF не записан"))

        shutil.copy(html, keep)
        if os.path.exists(out_pdf):
            warn("export_pdf: старый %s остался нетронутым — он устарел, не сдавай его"
                 % out_pdf)
        if failed:
            warn("export_pdf: PDF не собран:\n" + "\n".join(failed))
            warn("export_pdf: оставлен %s — напечатай в PDF из браузера (⌘P)" % keep)
            return 2
        print("export_pdf: PDF-движка нет — оставлен %s; напечатай в PDF из браузера (⌘P)\n"
              "  рекомендуемый движок: brew install typst" % keep)
        return 3
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("doc", nargs="+")
    ap.add_argument("-o", "--out")
    ap.add_argument("--corpus", nargs="*", default=None)
    ap.add_argument("--engine", default="auto")
    ap.add_argument("--md", "--bundle", dest="md",
                    help="markdown-пакет вместо PDF (несколько документов — под своими H1)")
    ap.add_argument("--strict", action="store_true",
                    help="неразрешённая ссылка — не сдача (rc=1)")
    a = ap.parse_args()

    if a.engine not in ENGINES:
        warn("export_pdf: неизвестный движок %s; допустимы: %s"
             % (a.engine, ", ".join(ENGINES))); return 2

    docs = [os.path.abspath(d) for d in a.doc]
    missing = [d for d in docs if not os.path.isfile(d)]
    if missing:
        warn("export_pdf: нет файла: %s" % ", ".join(missing)); return 2
    if len(docs) > 1 and not a.md:
        warn("export_pdf: несколько документов собираются только в markdown-пакет: "
             "--bundle ВЫХОД.md"); return 2

    if a.md:
        return build_markdown(docs, os.path.abspath(a.md), a.corpus, a.strict)
    out_pdf = os.path.abspath(a.out) if a.out else os.path.splitext(docs[0])[0] + ".pdf"
    return build_pdf(docs[0], out_pdf, a.corpus, a.engine, a.strict)


if __name__ == "__main__":
    sys.exit(main())
