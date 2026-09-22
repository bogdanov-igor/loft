#!/usr/bin/env python3
"""Целостность md-корпуса: битые [[wikilinks]]/![[embeds]]/относительные
ссылки (включая картинки ![alt](path) и reference-определения
«[ref]: путь»), ненайденные якоря #фрагментов и страницы-сироты.
Детерминированный, только stdlib. Не проверяются код-фенсы (```/~~~),
отступной код, инлайн-код и HTML-комментарии.

Usage: link_check.py <dir> [<dir> ...] [--no-orphans]
Exit: 0 — битых нет; 1 — есть битые ссылки; 2 — ошибка вызова.
"""
import argparse, html, os, re, sys, unicodedata, urllib.parse

# \\?\| — внутри GFM-таблиц разделитель алиаса экранируется как \| (стиль Obsidian).
# Алиас держит «]», если это не «]]»: в корпусе есть [[стр|[TO BE] Валидация]] —
# запрет на «]» делал такую строку не ссылкой вовсе, а её цель — сиротой.
# Цель необязательна: [[#якорь]] и [[#якорь|текст]] — ссылка внутри текущей
# страницы (Obsidian/Foam), её конвертер пишет для якорей той же страницы.
WIKILINK = re.compile(
    r"(!?)\[\[([^\]\|#\\]*)(?:#([^\]\|\\]*))?(?:\\?\|(?:[^\]]|\](?!\]))*)?\]\]")
LINK_OPEN = re.compile(r"!?\[[^\]\n]*\]\(")
# CommonMark link reference definition: «[ref]: путь "title"», отступ до трёх
# пробелов, путь в <…> либо без пробелов. Хвост после пути обязан быть
# title в кавычках — иначе строка вида «[термин]: длинное описание» не
# определение, а обычный текст (и её «цель» не проверяется).
LINK_DEF = re.compile(
    r"""^ {0,3}\[((?:[^\[\]\\]|\\.)+)\]:[ \t]*"""
    r"""(?:<([^<>\n]*)>|((?:[^\s\\]|\\.)+))"""
    r"""(?:[ \t]+(?:"[^"]*"|'[^']*'|\([^()]*\)))?[ \t]*$""")
# использование определения: [текст][ref] и [ref][]. Сокращённая форма [ref]
# от обычного текста в скобках неотличима — по ней не судим вовсе.
REF_USE = re.compile(r"!?\[((?:[^\[\]\\]|\\.)*)\]\[((?:[^\[\]\\]|\\.)*)\]")
HEADING = re.compile(r"^ {0,3}#{1,6}(?:[ \t]|$)")
FENCE = re.compile(r"^[ \t]*(`{3,}|~{3,})(.*)$")
LIST_ITEM = re.compile(r"^[ \t]{0,3}(?:[-*+]|\d{1,9}[.)])(?:[ \t]|$)")
TITLE_TAIL = re.compile(r"""[ \t]+(?:"[^"]*"|'[^']*'|\([^()]*\))[ \t]*$""")
SKIP_SCHEMES = ("http://", "https://", "mailto:", "tel:")
# любая схема URI (RFC 3986): по ней узнаём внешнюю ссылку для
# предупреждения о непроэкранированных «(»/«)»/пробеле в её url
URL_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
# --- цели фрагментов (#якорей) на странице -----------------------------------
HEADING_TEXT = re.compile(r"^ {0,3}#{1,6}[ \t]+(.*?)[ \t]*$")
ATX_CLOSE = re.compile(r"[ \t]+#+[ \t]*$")     # закрывающая решётка «## X ##»
# block-id Obsidian: «^id» в самом конце строки
BLOCK_ID = re.compile(r"(?:^|[ \t])\^([A-Za-z0-9-]+)[ \t]*$")
# <a name="X">, <a id="X">, id="X" на любом теге — так якорь живёт в сыром HTML
HTML_ANCHOR = re.compile(
    r"""<[a-zA-Z][^<>]*?\b(?:name|id)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'<>`]+))""")
HTML_TAG = re.compile(r"<[^<>]*>")
# разметка в тексте заголовка: [[стр|текст]] и [текст](url) отдают текст,
# маркеры выделения снимаются. «_» — только на границе слова: якорь
# «Получение_pan» это имя, а не курсив
WL_TEXT = re.compile(
    r"!?\[\[([^\]\|#]*)(?:#[^\]\|]*)?(?:\\?\|((?:[^\]]|\](?!\]))*))?\]\]")
MD_TEXT = re.compile(r"!?\[((?:[^\[\]]|\\.)*)\]\([^()]*\)")
EMPH = re.compile(r"\*+|~~+|`+|(?<![^\W_])_+|_+(?![^\W_])")
ESCAPED = re.compile(r"\\([!-/:-@\[-`{-~])")
WL_FRAG = re.compile(r"[\[\]|#\\]")            # так фрагмент пишет конвертер
# служебные страницы: входящих ссылок не имеют по назначению
ORPHAN_EXEMPT = ("home.md", "readme.md", "memory.md", "index.md")


def key(name):
    # Разрешение имён в стиле Foam/Obsidian: без регистра, NFC
    # (macOS отдаёт имена в NFD — прямое сравнение с NFC-ссылкой врёт).
    return unicodedata.normalize("NFC", name).casefold()


def ref_key(label):
    # Нормализация метки ссылки по CommonMark: пробелы схлопнуты, регистр снят.
    return key(re.sub(r"\s+", " ", label).strip())


def frag_key(name):
    # Якоря сверяются как имена файлов (регистр, NFC) плюс раскодированные
    # %XX: pandoc процентно кодирует всё не-ASCII в ссылке на якорь.
    return ref_key(urllib.parse.unquote(name))


def head_text(s):
    """Текст заголовка без markdown-разметки — то, с чем Obsidian сверяет
    фрагмент [[стр#Текст заголовка]]."""
    s = HTML_TAG.sub("", s)
    s = WL_TEXT.sub(lambda m: m.group(2) or m.group(1), s)
    s = MD_TEXT.sub(r"\1", s)
    return ESCAPED.sub(r"\1", EMPH.sub("", s))


def collect_anchors(line, masked, out):
    """Якоря строки: текст заголовка, block-id «^id» в конце строки, name=/id=
    в сыром HTML. Заголовок берётся из исходной строки (инлайн-код — часть его
    текста), но только пока он остаётся заголовком и в погашенной: «# x»
    внутри комментария или кода якоря не даёт."""
    # решётка заголовка — в первых четырёх символах (отступ до трёх пробелов):
    # дешёвая проверка вместо регулярки на каждой строке корпуса
    m = (HEADING_TEXT.match(masked) and HEADING_TEXT.match(line)
         if masked.find("#", 0, 4) >= 0 else None)
    if m:
        text = ATX_CLOSE.sub("", m.group(1))
        # разметка снимается, но и сырой вид годится: конвертер пишет
        # фрагмент, сняв лишь символы, которые закрыли бы ссылку
        for a in (head_text(text), WL_FRAG.sub("", text)):
            a = frag_key(a)
            if a:
                out.add(a)
    if "^" in masked:
        m = BLOCK_ID.search(masked)
        if m:                  # ссылка на блок пишется [[стр#^id]], сама метка
            out.add(frag_key(m.group(1)))          # в тексте — без решётки
            out.add(frag_key("^" + m.group(1)))
    if "<" in masked:
        for m in HTML_ANCHOR.finditer(masked):
            a = next((g for g in m.groups() if g), "")
            if not a:
                continue
            out.add(frag_key(a))
            u = html.unescape(a)   # в атрибуте якорь экранирован, в ссылке — нет
            if u != a:
                out.add(frag_key(u))


def warn(msg):
    # предупреждения — в stderr: stdout остаётся машиночитаемым отчётом
    sys.stderr.write("link_check: warning — %s\n" % msg)


def indent_width(line):
    if line[:1] not in (" ", "\t"):
        return 0
    w = 0
    for ch in line:
        if ch == " ":
            w += 1
        elif ch == "\t":
            w += 4 - (w % 4)
        else:
            break
    return w


def mask_spans(line, in_comment):
    """Гасит инлайн-код и HTML-комментарии (многострочные — по состоянию),
    сохраняя длину строки. Возвращает (строка, in_comment)."""
    n = len(line)
    if not in_comment and "`" not in line and "<!--" not in line:
        return line, False
    out, i = [], 0
    while i < n:
        if in_comment:
            j = line.find("-->", i)
            if j < 0:
                out.append(" " * (n - i)); i = n
            else:
                out.append(" " * (j + 3 - i)); i = j + 3; in_comment = False
            continue
        tick, cmt = line.find("`", i), line.find("<!--", i)
        if tick < 0 and cmt < 0:
            out.append(line[i:]); break
        if cmt >= 0 and (tick < 0 or cmt < tick):
            out.append(line[i:cmt]); out.append("    ")
            i, in_comment = cmt + 4, True
            continue
        out.append(line[i:tick])
        j = tick
        while j < n and line[j] == "`":
            j += 1
        run, k, end = j - tick, j, -1
        ticks = "`" * run
        while True:  # закрывает ровно такая же серия бэктиков (CommonMark)
            k = line.find(ticks, k)
            if k < 0:
                break
            start = k
            while start > j and line[start - 1] == "`":
                start -= 1
            m = k
            while m < n and line[m] == "`":
                m += 1
            if m - start == run:
                end = m
                break
            k = m
        if end > 0:
            out.append(" " * (end - tick)); i = end
        else:  # незакрытая серия — обычный текст
            out.append(line[tick:j]); i = j
    return "".join(out), in_comment


def realpath(path, _cache={}):
    r = _cache.get(path)
    if r is None:
        r = _cache[path] = os.path.realpath(path)
    return r


def md_targets(line):
    """Назначения [текст](путь) и ![alt](путь): <путь с пробелами>,
    парные скобки в имени файла, экранированные скобки, title в кавычках.
    Отдаёт пары (цель, предупреждения): у url со схемой (http, mailto и
    прочие), не взятого в <…>, непроэкранированные «(», «)» или пробел —
    такую ссылку рвут Confluence и наивные md-рендеры, хоть здесь она и
    резолвится верно (парные скобки посчитаны)."""
    out, n = [], len(line)
    for m in LINK_OPEN.finditer(line):
        i = m.end()
        while i < n and line[i] in " \t":
            i += 1
        angle = i < n and line[i] == "<"
        if angle:
            j = line.find(">", i + 1)
            if j < 0 or line.find(")", j + 1) < 0:
                continue
            dest = line[i + 1:j]
        else:
            depth, j = 0, i
            while j < n:
                ch = line[j]
                if ch == "\\" and j + 1 < n:
                    j += 2
                    continue
                if ch == "(":
                    depth += 1
                elif ch == ")":
                    if depth == 0:
                        break
                    depth -= 1
                j += 1
            if j >= n:
                continue
            dest = TITLE_TAIL.sub("", line[i:j])
        dest = dest.strip().replace("\\(", "(").replace("\\)", ")").replace("\\ ", " ")
        if not dest:
            continue
        warns = []
        if not angle and URL_SCHEME.match(dest):
            if "(" in dest or ")" in dest:
                warns.append("скобки в url без экранирования")
            if " " in dest:
                warns.append("пробел в url")
        out.append((dest, warns))
    return out


def build_index(roots):
    """Индекс целей: по basename, по относительному пути и по хвосту пути.
    Каждое имя регистрируется и с .md, и без — как пишут wikilinks."""
    md_files, by_key, by_rel, by_tail = [], {}, {}, {}
    for root in roots:
        for dirpath, dirs, files in os.walk(root):
            dirs.sort(); files.sort()  # порядок обхода не зависит от ФС
            for f in files:
                p = os.path.join(dirpath, f)
                segs = [key(s) for s in p.replace("\\", "/").split("/")
                        if s not in ("", ".")]
                dirsegs = tuple(segs[:-1])
                names = [key(f)]
                base, ext = os.path.splitext(f)
                if ext.lower() == ".md":
                    md_files.append(p)
                    names.append(key(base))
                for nm in names:
                    by_key.setdefault(nm, []).append(p)
                    by_rel.setdefault("/".join(dirsegs + (nm,)), []).append(p)
                    by_tail.setdefault(nm, []).append((dirsegs, p))
    for d in (by_key, by_rel):
        for k in d:
            d[k] = sorted(set(d[k]))
    return md_files, by_key, by_rel, by_tail


def resolve(target, index):
    """Кандидаты в лексическом порядке. Цель с «/» — как в Obsidian:
    точное совпадение относительного пути, затем совпадение по хвосту;
    голое имя — по basename."""
    _md, by_key, by_rel, by_tail = index
    t = target.replace("\\", "/").strip().strip("/")
    while t.startswith("./"):
        t = t[2:]
    if not t:
        return []
    if "/" in t:
        # «..» отбрасывается: относительных wikilinks нет ни у Obsidian,
        # ни у Foam — цель ищется по хвосту пути
        segs = [key(s) for s in t.split("/") if s not in ("", ".", "..")]
        if not segs:
            return []
        hit = by_rel.get("/".join(segs))
        if hit:
            return hit
        need, last = tuple(segs[:-1]), segs[-1]
        k = len(need)
        return sorted({p for dirsegs, p in by_tail.get(last, ())
                       if len(dirsegs) >= k and (not k or dirsegs[-k:] == need)})
    return by_key.get(key(t), [])


def note_frag(frag, target, display, path, lineno, state):
    """Фрагмент к сверке. Якоря целевой страницы собирает её собственный —
    единственный — проход, поэтому сверка отложена до конца обхода."""
    pending = state[5]
    parts = [p for p in frag.split("#") if p.strip()]
    # вложенный путь заголовков [[стр#H1#H2]] ведёт к последнему из них
    if parts and target.lower().endswith(".md"):
        pending.append((path, lineno, display, realpath(target), parts[-1].strip()))


def check_rel(target, path, lineno, state):
    """Относительная цель (md-ссылка, картинка, reference-определение):
    считается проверенной и, если файла нет, попадает в битые. Фрагмент
    сверяется с якорями цели, «#якорь» без файла — якорь этой же страницы."""
    total, broken, incoming = state[0], state[1], state[2]
    if target.startswith(SKIP_SCHEMES):
        return
    raw, _, frag = target.partition("#")
    rel = urllib.parse.unquote(raw)
    if not rel:
        if frag.strip():             # [текст](#якорь) — цель текущая страница
            total[0] += 1
            note_frag(frag, path, target, path, lineno, state)
        return
    total[0] += 1
    p = os.path.normpath(os.path.join(os.path.dirname(path), rel))
    if os.path.exists(p):
        incoming.add(realpath(p))
        if frag.strip():
            note_frag(frag, p, target, path, lineno, state)
    else:
        broken.append((path, lineno, target))


def scan(path, index, state):
    """Один проход по файлу: снимает код и комментарии, отдаёт ссылки и
    попутно — якоря самой страницы (второй раз файл не читается)."""
    total, broken, incoming, ambiguous, anchors = state[:5]
    warns_count = state[6]
    names = anchors.setdefault(realpath(path), set())
    in_fence, fence_ch, fence_len = False, "", 0
    in_comment = in_code_indent = in_list = False
    prev_blank = True
    prev_def = False
    defs, uses = set(), []
    with open(path, encoding="utf-8", errors="replace") as fh:
        for lineno, raw in enumerate(fh, 1):
            line = raw.rstrip("\n")
            blank = not line.strip()
            # определение не прерывает абзац (CommonMark): открыть его может
            # только пустая строка, заголовок или предыдущее определение
            can_def = prev_blank or prev_def or bool(HEADING.match(line))
            prev_def = False
            if in_fence:
                m = FENCE.match(line)
                # закрывает фенс того же символа и не короче (CommonMark)
                if (m and m.group(1)[0] == fence_ch
                        and len(m.group(1)) >= fence_len and not m.group(2).strip()):
                    in_fence = False
                prev_blank = blank
                continue
            if not in_comment:
                m = FENCE.match(line)
                if m and not (m.group(1)[0] == "`" and "`" in m.group(2)):
                    in_fence, in_code_indent = True, False
                    fence_ch, fence_len = m.group(1)[0], len(m.group(1))
                    prev_blank = blank
                    continue
                indent = indent_width(line)
                if in_code_indent:
                    if blank or indent >= 4:
                        prev_blank = blank
                        continue
                    in_code_indent = False
                elif not blank and indent >= 4 and prev_blank and not in_list:
                    in_code_indent = True
                    prev_blank = blank
                    continue
                if not blank:  # отступ в списке — не код, а продолжение пункта
                    if LIST_ITEM.match(line):
                        in_list = True
                    elif indent == 0:
                        in_list = False
            masked, in_comment = mask_spans(line, in_comment)
            prev_blank = blank
            if not blank:
                collect_anchors(line, masked, names)
            m = LINK_DEF.match(masked) if can_def and not blank else None
            prev_def = bool(m)
            if m:
                # первое определение метки выигрывает, повторное инертно
                if ref_key(m.group(1)) not in defs:
                    defs.add(ref_key(m.group(1)))
                    dest = m.group(2) if m.group(2) is not None else m.group(3)
                    dest = dest.strip().replace("\\(", "(").replace(
                        "\\)", ")").replace("\\ ", " ")
                    if dest:
                        check_rel(dest, path, lineno, state)
                continue                  # строка-определение — целиком блок
            for m in REF_USE.finditer(masked):
                label = m.group(2).strip() or m.group(1).strip()
                if label:
                    uses.append((lineno, label))
            for _bang, target, frag in WIKILINK.findall(masked):
                t, fr = target.strip(), frag.strip()
                if not t and not fr:
                    continue          # [[]] и [[|текст]] — не ссылка
                total[0] += 1
                if not t:             # [[#якорь]] — цель эта же страница,
                    # входящей ссылкой она себе не становится (иначе сирот нет)
                    note_frag(fr, path, "[[#%s]]" % fr, path, lineno, state)
                    continue
                hits = resolve(t, index)
                if hits:
                    if len(hits) > 1 and key(t) not in ambiguous:
                        ambiguous.add(key(t))
                        warn("неоднозначно: %d кандидатов для [[%s]] (%s:%d), "
                             "выбран %s" % (len(hits), t, path, lineno, hits[0]))
                    incoming.add(realpath(hits[0]))
                    if fr:
                        note_frag(fr, hits[0], "[[%s#%s]]" % (t, fr),
                                  path, lineno, state)
                else:
                    broken.append((path, lineno, "[[%s]]" % t))
            for href, warns in md_targets(masked):
                for reason in warns:
                    warns_count[0] += 1
                    sys.stderr.write("WARN %s:%d → %s  (%s)\n"
                                      % (path, lineno, href, reason))
                check_rel(href, path, lineno, state)
    # [текст][ref] без определения — не битая ссылка, а вероятная опечатка:
    # цели у неё нет вовсе, и в скобках мог оказаться обычный текст
    seen = set()
    for lineno, label in uses:
        k = ref_key(label)
        if k in defs or k in seen:
            continue
        seen.add(k)
        warn("нет определения для ссылки [%s] (%s:%d)" % (label, path, lineno))


def main(argv):
    ap = argparse.ArgumentParser(
        prog="link_check", description=__doc__.split("\n\n")[0],
        allow_abbrev=False,  # --no-orphan не должен молча сходить за --no-orphans
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Exit: 0 — битых нет; 1 — есть битые ссылки; 2 — ошибка вызова.")
    ap.add_argument("dirs", nargs="+", metavar="dir", help="каталоги корпуса")
    ap.add_argument("--no-orphans", action="store_true",
                    help="не искать страницы-сироты")
    args = ap.parse_args(argv)  # неизвестный флаг — SystemExit(2), а не тишина

    roots = []
    for r in args.dirs:
        if os.path.isdir(r):
            roots.append(r)
        else:
            warn("каталог не существует и пропущен: %s" % r)
    if not roots:
        sys.stderr.write("link_check: ни один из каталогов не существует\n")
        return 2

    index = build_index(roots)
    md_files = index[0]
    total, broken, incoming, ambiguous = [0], [], set(), set()
    anchors, pending, warns_count = {}, [], [0]
    state = (total, broken, incoming, ambiguous, anchors, pending, warns_count)
    for path in md_files:
        scan(path, index, state)

    # якоря целевых страниц собраны тем же обходом — сверка после него.
    # Цель за пределами проверяемых каталогов якорей не имеет: о ней не судим
    missing = 0
    for path, lineno, display, target, frag in pending:
        names = anchors.get(target)
        if names is not None and frag_key(frag) not in names:
            missing += 1
            broken.append((path, lineno, display + "  (якорь не найден)"))

    orphans = []
    if not args.no_orphans:
        for p in md_files:
            name = key(os.path.basename(p))
            if name.startswith("_") or name in ORPHAN_EXEMPT:
                continue
            if realpath(p) not in incoming:
                orphans.append(p)

    summary = ("ссылок проверено: %d · битых: %d · сирот: %d"
               % (total[0], len(broken), len(orphans)))
    if missing:   # без ненайденных якорей сводка выглядит как раньше
        summary += " · якорей не найдено: %d" % missing
    if warns_count[0]:   # без предупреждений сводка выглядит как раньше
        summary += " · предупреждений: %d" % warns_count[0]
    print(summary)
    for path, lineno, target in broken:
        print("BROKEN  %s:%d → %s" % (path, lineno, target))
    for p in orphans:
        print("ORPHAN  %s" % p)
    return 1 if broken else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
