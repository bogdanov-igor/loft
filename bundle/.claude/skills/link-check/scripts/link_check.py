#!/usr/bin/env python3
"""Целостность md-корпуса: битые [[wikilinks]]/![[embeds]]/относительные
ссылки (включая картинки ![alt](path)) и страницы-сироты.
Детерминированный, только stdlib. Строки внутри код-фенсов (```/~~~)
не проверяются.

Usage: link_check.py <dir> [<dir> ...] [--no-orphans]
Exit: 0 — битых нет; 1 — есть битые ссылки; 2 — ошибка вызова.
"""
import os, re, sys, unicodedata, urllib.parse

# \\?\| — внутри GFM-таблиц разделитель алиаса экранируется как \| (стиль Obsidian)
WIKILINK = re.compile(r"(!?)\[\[([^\]\|#\\]+)(?:#[^\]\|\\]*)?(?:\\?\|[^\]]*)?\]\]")
MDLINK = re.compile(r"!?\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
FENCE = re.compile(r"^\s*(```|~~~)")
SKIP_SCHEMES = ("http://", "https://", "mailto:", "tel:", "#")


def key(name):
    # Разрешение basename в стиле Foam/Obsidian: без регистра, NFC
    # (macOS отдаёт имена в NFD — прямое сравнение с NFC-ссылкой врёт).
    return unicodedata.normalize("NFC", name).casefold()


def main(argv):
    roots = [a for a in argv if not a.startswith("--")]
    if not roots:
        print(__doc__); return 2
    check_orphans = "--no-orphans" not in argv
    missing = [r for r in roots if not os.path.isdir(r)]
    for r in missing:
        print("link_check: warning — каталог не существует и пропущен: %s" % r)
    roots = [r for r in roots if os.path.isdir(r)]
    if not roots:
        print("link_check: ни один из каталогов не существует"); return 2

    md_files, all_files = [], {}
    for root in roots:
        for dirpath, _dirs, files in os.walk(root):
            for f in files:
                p = os.path.join(dirpath, f)
                # первое вхождение выигрывает; дубли basename в корпусе
                # редки и всплывают в аудите
                all_files.setdefault(key(f), p)
                base, ext = os.path.splitext(f)
                if ext.lower() == ".md":
                    md_files.append(p)
                    all_files.setdefault(key(base), p)

    total, broken, incoming = 0, [], set()
    for path in md_files:
        in_fence = False
        with open(path, encoding="utf-8", errors="replace") as fh:
            for lineno, line in enumerate(fh, 1):
                if FENCE.match(line):
                    in_fence = not in_fence
                    continue
                if in_fence:
                    continue
                for _bang, target in WIKILINK.findall(line):
                    total += 1
                    t = target.strip()
                    hit = all_files.get(key(t)) or all_files.get(key(os.path.basename(t))) \
                        or all_files.get(key(t + ".md")) or all_files.get(key(os.path.basename(t) + ".md"))
                    if hit:
                        incoming.add(os.path.realpath(hit))
                    else:
                        broken.append((path, lineno, "[[%s]]" % t))
                for href in MDLINK.findall(line):
                    if href.startswith(SKIP_SCHEMES):
                        continue
                    total += 1
                    rel = urllib.parse.unquote(href.split("#", 1)[0])
                    if not rel:
                        continue
                    p = os.path.normpath(os.path.join(os.path.dirname(path), rel))
                    if os.path.exists(p):
                        incoming.add(os.path.realpath(p))
                    else:
                        broken.append((path, lineno, href))

    orphans = []
    if check_orphans:
        for p in md_files:
            name = os.path.basename(p)
            if name.startswith("_") or name in ("Home.md", "README.md", "MEMORY.md"):
                continue
            if os.path.realpath(p) not in incoming:
                orphans.append(p)

    print("ссылок проверено: %d · битых: %d · сирот: %d"
          % (total, len(broken), len(orphans)))
    for path, lineno, target in broken:
        print("BROKEN  %s:%d → %s" % (path, lineno, target))
    for p in orphans:
        print("ORPHAN  %s" % p)
    return 1 if broken else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
