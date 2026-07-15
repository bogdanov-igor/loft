#!/usr/bin/env bash
# Уборка машинерии specos/skillforge из проекта, который теперь ведёт loft.
#
#   bash .claude/skills/migrate-specos/sweep.sh            # только отчёт
#   bash .claude/skills/migrate-specos/sweep.sh --apply    # карантин
#
# Переносится ТОЛЬКО машинерия. Состояние проекта (wiki/, spec/, docs/,
# memory/, BACKLOG, QUESTIONS, .secrets.env) не трогается никогда.
# Ничего не удаляется: всё уезжает в .loft-migration/<ts>/ с MANIFEST.md,
# где каждая строка — команда mv для отката.
set -uo pipefail
PROJECT="${CLAUDE_PROJECT_DIR:-$PWD}"
cd "$PROJECT" || exit 1
APPLY=0
[ "${1:-}" = "--apply" ] && APPLY=1

# Машинерия: бандлы, дистрибутивы и служебное состояние движков specos/skillforge.
MACHINERY=()
for p in specos skillforge; do [ -d "$p" ] && MACHINERY+=("$p"); done
for f in specos-*.tar.gz specos-*.tar.gz.sha256 skillforge_*.tgz skillforge_*.tgz.sha256; do
  [ -f "$f" ] && MACHINERY+=("$f")
done
for f in .data/.specos-* .data/runs.jsonl .data/memory-index.json; do
  [ -e "$f" ] && MACHINERY+=("$f")
done
[ -d .data/bin ] && ls .data/bin/specos-* >/dev/null 2>&1 && MACHINERY+=(".data/bin")
[ -d .data/backup ] && MACHINERY+=(".data/backup")

# Неоднозначное: показываем, решает владелец — скрипт не гадает о чужих файлах.
FLAGGED=()
[ -d "доработка" ] && FLAGGED+=("доработка/ — временный хак chat-render? посмотреть и решить")
[ -d .specweave ] && FLAGGED+=(".specweave/ — кэш specweave (26МБ sqlite); восстановим при разморозке v2 переиндексацией")
for b in .claude.bak.*; do
  [ -d "$b" ] && FLAGGED+=("$b — бэкап прежнего .claude; внутри может жить память specos (memory/knowledge) — ценное перенести скиллом remember, потом решить судьбу")
done
if [ -f .mcp.json ] && grep -q specos .mcp.json 2>/dev/null; then
  FLAGGED+=(".mcp.json — всё ещё содержит specos-серверы (инсталлер обычно уводит его в бэкап; проверь)")
fi

echo "== sweep: $PROJECT =="
if [ "${#MACHINERY[@]}" -gt 0 ]; then
  echo "MACHINERY (${#MACHINERY[@]}) — уедет в карантин при --apply:"
  printf '  %s\n' "${MACHINERY[@]}"
else
  echo "MACHINERY (0) — машинерии specos/skillforge не найдено"
fi
if [ "${#FLAGGED[@]}" -gt 0 ]; then
  echo "FLAGGED (${#FLAGGED[@]}) — остаётся на месте, решает владелец:"
  printf '  %s\n' "${FLAGGED[@]}"
fi

[ "$APPLY" -eq 1 ] || exit 0
[ "${#MACHINERY[@]}" -gt 0 ] || { echo "нечего переносить"; exit 0; }

TS="$(date +%Y%m%d%H%M%S)"
Q=".loft-migration/$TS"
mkdir -p "$Q"
MANIFEST="$Q/MANIFEST.md"
{
  echo "# Карантин specos-машинерии от $TS"
  echo
  echo "Откат любой строки: выполнить её \`mv\` в обратную сторону."
  echo
} > "$MANIFEST"
for p in "${MACHINERY[@]}"; do
  dest="$Q/$(dirname "$p")"
  mkdir -p "$dest"
  mv "$p" "$dest/" || { echo "FAIL: не перенеслось: $p"; exit 1; }
  echo "- \`mv '$Q/$p' '$p'\` — было: $p" >> "$MANIFEST"
done
echo "перенесено: ${#MACHINERY[@]} → $Q (манифест: $MANIFEST)"

# Ре-аудит переживает сессию строкой в очереди, а не чьей-то памятью.
if [ -f BACKLOG.md ] && ! grep -q "src:migrate-specos" BACKLOG.md; then
  printf -- '- [ ] P1 | корпус | Ре-аудит после миграции со specos: tz-audit + перенос ценного из .claude.bak (memory/knowledge) в memory/ | ev:%s | src:migrate-specos\n' "$MANIFEST" >> BACKLOG.md
  echo "в BACKLOG.md добавлена строка ре-аудита"
fi
exit 0
