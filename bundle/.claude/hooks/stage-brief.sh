#!/usr/bin/env bash
# SessionStart (resume|compact): напомнить об открытой стадии.
# Открытая стадия — каталог stages/NNN-*/ с brief.md и без report.md.
# Печатаем одну строку только когда такая стадия есть; иначе молчим,
# чтобы не платить контекстом на каждом старте. Любой сбой — тихий выход.
set -uo pipefail
PROJECT="${CLAUDE_PROJECT_DIR:-$PWD}"
[ -d "$PROJECT/stages" ] || exit 0
open=""
for d in "$PROJECT"/stages/*/; do
  [ -f "$d/brief.md" ] || continue
  [ -f "$d/report.md" ] && continue
  open="$open ${d#"$PROJECT"/}brief.md"
done
[ -n "$open" ] || exit 0
printf 'loft: открытая стадия:%s — перечитай бриф и критерии готовности перед продолжением.\n' "$open"
exit 0
