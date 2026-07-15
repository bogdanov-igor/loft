#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generate wiki/Home.md — a Map-of-Content landing note with the full Confluence
page tree as nested wikilinks, plus space metadata. Reads wiki/.pagemap.json and
wiki/.space.json (space key/name, snapshot date — written by convert.py).
Project-agnostic: no space-specific texts here."""
import json, os, sys

WIKI = sys.argv[1]
pm = json.load(open(os.path.join(WIKI, ".pagemap.json"), encoding="utf-8"))
try:
    meta = json.load(open(os.path.join(WIKI, ".space.json"), encoding="utf-8"))
except FileNotFoundError:
    meta = {}
KEY = meta.get("key", "")
NAME = meta.get("name", "")
SNAPSHOT = meta.get("snapshot", "")

# children already stored; order by 'order'
def kids(pid):
    return sorted(pm[pid]["children"], key=lambda k: pm[k]["order"])

roots = sorted([p for p, r in pm.items() if not r["parent"]], key=lambda k: pm[k]["order"])
home_id = roots[0]

def link(pid):
    return f"[[{pm[pid]['basename']}|{pm[pid]['title']}]]"

lines = []
def walk(pid, depth):
    lines.append("  " * depth + f"- {link(pid)}")
    for k in kids(pid):
        walk(k, depth + 1)

# top sections = children of home page
sections = kids(home_id)

head = " — ".join(x for x in (KEY, NAME) if x) or pm[home_id]["title"]
out = []
out.append("---")
out.append(f'title: "{head}"')
if KEY:
    out.append(f"space: {KEY}")
out.append("tags: [moc, confluence-import]")
out.append("---")
out.append("")
out.append(f"# {head}")
out.append("")
out.append(f"> Пространство Confluence **{KEY or pm[home_id]['title']}**"
           + (f" ({NAME})" if NAME else "")
           + f", {len(pm)} страниц, перенесено в Markdown с сохранением "
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
out.append("## 🗂️ Полное дерево страниц")
out.append("")
walk(home_id, 0)
for r in roots[1:]:
    walk(r, 0)
out.extend(lines)
out.append("")
out.append("---")
out.append("")
out.append("*Сгенерировано автоматически из выгрузки Confluence. "
           "Картинки — в `assets/`, документы (PDF/WSDL/…) — в `attachments/`.*")

open(os.path.join(WIKI, "Home.md"), "w", encoding="utf-8").write("\n".join(out) + "\n")
print(f"Home.md written: {len(pm)} pages, {len(sections)} top sections, "
      f"{len(out)} lines")
