#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generate wiki/Home.md — a Map-of-Content landing note with the full Confluence
page tree as nested wikilinks, plus space metadata. Reads wiki/.pagemap.json and
wiki/.space.json (space key/name, snapshot date, per-space metadata — written by
convert.py).

One wiki may hold several spaces (a second export ingested into the same dir):
the tree is grouped by the `space` of each pagemap entry — the current space
(`key` of .space.json) leads, every other space gets its own section with its
own roots and snapshot date, taken from the `spaces` dict of .space.json.
Without that grouping the roots of a foreign space became extra roots of the
current one.
Project-agnostic: no space-specific texts here."""
import json, os, sys
from collections import OrderedDict

for _s in (sys.stdout, sys.stderr):                # Cyrillic under LC_ALL=C
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

if len(sys.argv) < 2:
    print("make_index.py <wiki-dir>\n"
          "  собирает <wiki>/Home.md из <wiki>/.pagemap.json и .space.json,\n"
          "  которые пишет convert.py", file=sys.stderr)
    sys.exit(2)
WIKI = sys.argv[1]
PM_PATH = os.path.join(WIKI, ".pagemap.json")
if not os.path.exists(PM_PATH):
    print(f"make_index.py: нет {PM_PATH} — сначала прогони convert.py",
          file=sys.stderr)
    sys.exit(2)
try:
    pm = json.load(open(PM_PATH, encoding="utf-8"))
except json.JSONDecodeError as e:
    print(f"make_index.py: {PM_PATH} побит ({e}) — перегенерируй convert.py",
          file=sys.stderr)
    sys.exit(2)
if not pm:
    print(f"make_index.py: {PM_PATH} пуст — страниц нет", file=sys.stderr)
    sys.exit(2)
try:
    meta = json.load(open(os.path.join(WIKI, ".space.json"), encoding="utf-8"))
except (FileNotFoundError, json.JSONDecodeError):
    meta = {}
KEY = meta.get("key", "")
NAME = meta.get("name", "")
SNAPSHOT = meta.get("snapshot_date") or meta.get("snapshot", "")  # до 2.3 — snapshot
SPACES = meta.get("spaces") if isinstance(meta.get("spaces"), dict) else {}

# ---- group pages by space. Entries without `space` come from a map written
# before 2.1, when a wiki could hold one space only -> they are the current one.
groups = OrderedDict()
for pid, rec in pm.items():
    groups.setdefault(rec.get("space") or KEY, []).append(pid)
if KEY not in groups:            # .space.json disagrees with the map (renamed
    KEY = next(iter(groups))     # key, hand edit): lead with the map's first
    info = SPACES.get(KEY) or {}
    NAME = info.get("name", NAME)
    SNAPSHOT = info.get("snapshot_date") or info.get("snapshot") or SNAPSHOT
OTHERS = sorted(k for k in groups if k != KEY)

# children already stored; order by 'order'. A child may be missing from the
# map (removed page whose parent survived) -- skip it instead of crashing.
def kids(pid):
    return sorted((k for k in pm[pid]["children"] if k in pm),
                  key=lambda k: pm[k]["order"])

def roots_of(key):
    """Pages of the space with no parent inside it (a parent in another space
    or gone from the map makes the page a root of its own tree)."""
    own = set(groups[key])
    return sorted((p for p in groups[key]
                   if not pm[p]["parent"] or pm[p]["parent"] not in own),
                  key=lambda p: pm[p]["order"])

roots = roots_of(KEY)
if not roots:
    print(f"make_index.py: в {PM_PATH} нет корневой страницы — карта битая",
          file=sys.stderr)
    sys.exit(2)
home_id = roots[0]

def link(pid):
    return f"[[{pm[pid]['basename']}|{pm[pid]['title']}]]"

def walk(pid, depth, acc):
    acc.append("  " * depth + f"- {link(pid)}")
    for k in kids(pid):
        walk(k, depth + 1, acc)

def tree_of(key):
    acc = []
    for r in roots_of(key):
        walk(r, 0, acc)
    return acc

# top sections = children of home page
sections = kids(home_id)

head = " — ".join(x for x in (KEY, NAME) if x) or pm[home_id]["title"]

def yaml_escape(s):                    # a quote in the space name broke the fm
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'

out = []
out.append("---")
out.append(f"title: {yaml_escape(head)}")
if KEY:
    out.append(f"space: {KEY}")
out.append("tags: [moc, confluence-import]")
out.append("---")
out.append("")
out.append(f"# {head}")
out.append("")
out.append(f"> Пространство Confluence **{KEY or pm[home_id]['title']}**"
           + (f" ({NAME})" if NAME else "")
           + f", {len(groups[KEY])} страниц, перенесено в Markdown с сохранением "
             "структуры, кода, диаграмм и связей.")
out.append("")
if SNAPSHOT:
    out.append(f"Снапшот Confluence: {SNAPSHOT}")
    out.append("")
out.append(f"**Оригинальная страница:** {link(home_id)}")
out.append("")
out.append("## 📂 Разделы верхнего уровня")
out.append("")
for s in sections:
    out.append(f"- {link(s)}")
# also non-home roots (e.g. pages outside the home tree)
for r in roots[1:]:
    out.append(f"- {link(r)}")
out.append("")
out.append("## 🗂️ Полное дерево страниц"
           + (f" — {KEY}" if OTHERS and KEY else ""))
out.append("")
out.extend(tree_of(KEY))
# other spaces sharing this wiki: own heading, own tree, own snapshot date
for k in OTHERS:
    info = SPACES.get(k) or {}
    nm = info.get("name") or ""
    snap = info.get("snapshot_date") or info.get("snapshot") or ""
    out.append("")
    out.append(f"## 🗂️ Спейс {k}" + (f" — {nm}" if nm else ""))
    out.append("")
    out.append(f"{len(groups[k])} страниц"
               + (f", снапшот Confluence: {snap}" if snap else
                  ", дата снапшота неизвестна"))
    out.append("")
    out.extend(tree_of(k))
out.append("")
out.append("---")
out.append("")
out.append("*Сгенерировано автоматически из выгрузки Confluence. "
           "Картинки — в `assets/`, документы (PDF/WSDL/…) — в `attachments/`.*")

open(os.path.join(WIKI, "Home.md"), "w", encoding="utf-8").write("\n".join(out) + "\n")
print(f"Home.md written: {len(pm)} pages, {len(sections)} top sections, "
      f"{len(out)} lines"
      + (f"; spaces: {KEY} + " + ", ".join(OTHERS) if OTHERS else ""))
