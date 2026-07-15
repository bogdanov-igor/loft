#!/usr/bin/env bash
# Loft installer: копирует ядро в проект.
# Usage: bash install.sh /path/to/project   (без аргумента — в текущий каталог)
set -euo pipefail
SRC="$(cd "$(dirname "$0")" && pwd -P)"
DEST="${1:-$PWD}"
[ -d "$DEST" ] || { echo "loft: нет такого каталога: $DEST" >&2; exit 1; }
DEST="$(cd "$DEST" && pwd -P)"
if [ "$DEST" = "$SRC" ]; then
  echo "loft: это каталог самого loft — запускай из корня проекта:" >&2
  echo "      cd /path/to/project && bash loft/install.sh" >&2
  exit 1
fi

# .claude — всегда реальный каталог, никогда симлинк (симлинки ломают
# резолв путей хуков и пер-проектность).
SPECOS_PREV=0
if [ -e "$DEST/.claude" ] || [ -L "$DEST/.claude" ]; then
  grep -qs 'specos-managed' "$DEST/.claude/CLAUDE.md" && SPECOS_PREV=1
  BAK="$DEST/.claude.bak.$(date +%Y%m%d%H%M%S)"
  mv "$DEST/.claude" "$BAK"
  echo "loft: прежний .claude перемещён в ${BAK##*/}"
fi
cp -R "$SRC/bundle/.claude" "$DEST/.claude"
tr -d '[:space:]' < "$SRC/VERSION" > "$DEST/.claude/VERSION"
chmod +x "$DEST/.claude/hooks/"*.sh "$DEST/.claude/skills/migrate-specos/sweep.sh"

# Скиллы проекта переживают переустановку: каталоги скиллов, которых ядро
# не поставляет, переносятся из прежнего .claude. Исключение — прежний
# .claude принадлежал specos (маркер specos-managed): его 28 скиллов не
# проектные, а specos'овские, и должны остаться в бэкапе. Переносим тогда
# только то, чего нет в specos wire-списке (если список сохранился).
restored=""
preserve_skill() {
  local d="$1" name
  [ -d "$d" ] || return 0
  name="$(basename "$d")"
  [ "$name" = "_user" ] && return 0
  if [ "$SPECOS_PREV" -eq 1 ] && [ -f "$DEST/.data/.specos-wire-skills.list" ] \
     && grep -qx "$name" "$DEST/.data/.specos-wire-skills.list"; then
    return 0
  fi
  if [ "$SPECOS_PREV" -eq 1 ] && [ ! -f "$DEST/.data/.specos-wire-skills.list" ]; then
    return 0   # specos без wire-списка: ничего не тащим, скиллы остаются в бэкапе
  fi
  if [ ! -d "$DEST/.claude/skills/$name" ]; then
    cp -R "$d" "$DEST/.claude/skills/$name"
    restored="$restored $name"
  fi
}
if [ -n "${BAK:-}" ] && [ -d "$BAK/skills" ]; then
  if [ -f "$BAK/_protocol.md" ]; then      # маркер SkillForge: проектные только в _user/
    for d in "$BAK/skills/_user"/*/; do preserve_skill "$d"; done
  else
    for d in "$BAK/skills"/*/ "$BAK/skills/_user"/*/; do preserve_skill "$d"; done
  fi
  [ -n "$restored" ] && echo "loft: перенесены проектные скиллы:$restored"
  [ "$SPECOS_PREV" -eq 1 ] && [ ! -f "$DEST/.data/.specos-wire-skills.list" ] \
    && echo "loft: прежний .claude был specos-managed без wire-списка — скиллы остались в бэкапе; нужные проектные перенеси руками"
fi

# Проектные агенты переживают переустановку по той же логике, что и скиллы.
restored_ag=""
if [ -n "${BAK:-}" ] && [ -d "$BAK/agents" ] && [ ! -f "$BAK/_protocol.md" ]; then
  for f in "$BAK/agents"/*.md; do
    [ -f "$f" ] || continue
    name="$(basename "$f")"
    if [ "$SPECOS_PREV" -eq 1 ]; then
      if [ -f "$DEST/.data/.specos-wire-agents.list" ] \
         && grep -qx "$name" "$DEST/.data/.specos-wire-agents.list"; then continue; fi
      [ -f "$DEST/.data/.specos-wire-agents.list" ] || continue
    fi
    if [ ! -f "$DEST/.claude/agents/$name" ]; then
      cp "$f" "$DEST/.claude/agents/$name"
      restored_ag="$restored_ag $name"
    fi
  done
  [ -n "$restored_ag" ] && echo "loft: перенесены проектные агенты:$restored_ag"
  [ "$SPECOS_PREV" -eq 1 ] && [ ! -f "$DEST/.data/.specos-wire-agents.list" ] \
    && echo "loft: specos без wire-списка агентов — агенты остались в бэкапе; нужные проектные перенеси руками"
fi

# Сиды: создаём только отсутствующее — состояние проекта не перезаписывается.
mkdir -p "$DEST/memory/lessons" "$DEST/memory/antipatterns" \
         "$DEST/memory/patterns" "$DEST/memory/structures" \
         "$DEST/stages" "$DEST/spec" "$DEST/inbox"
for d in memory/lessons memory/antipatterns memory/patterns memory/structures stages spec inbox; do
  touch "$DEST/$d/.gitkeep"
done
for f in BACKLOG.md QUESTIONS.md; do
  [ -f "$DEST/$f" ] || cp "$SRC/bundle/seed/$f" "$DEST/$f"
done
[ -f "$DEST/memory/MEMORY.md" ] || cp "$SRC/bundle/seed/MEMORY.md" "$DEST/memory/MEMORY.md"

# Секреты — вне git (правило 8 контракта).
touch "$DEST/.gitignore"
grep -qxF ".secrets.env" "$DEST/.gitignore" || printf '%s\n' ".secrets.env" >> "$DEST/.gitignore"

# Граф корпуса: [[wikilinks]] — это Foam/Obsidian-формат; рекомендация
# расширения даёт граф в VS Code одним кликом. Только если рекомендаций нет.
if [ ! -f "$DEST/.vscode/extensions.json" ]; then
  mkdir -p "$DEST/.vscode"
  printf '{\n  "recommendations": ["foam.foam-vscode", "bierner.markdown-mermaid"]\n}\n' \
    > "$DEST/.vscode/extensions.json"
fi

# MCP: loft не тянет серверов. Специальный случай — specos'овский .mcp.json
# (serena+playwright+memory = ~20–30k токенов схем в каждой сессии): уводим
# в бэкап, MCP-налог не переезжает. Прочие .mcp.json не трогаем.
if [ -f "$DEST/.mcp.json" ]; then
  if grep -q 'specos' "$DEST/.mcp.json" 2>/dev/null; then
    MBAK="$DEST/.mcp.json.bak.$(date +%Y%m%d%H%M%S)"
    mv "$DEST/.mcp.json" "$MBAK"
    echo "loft: specos'овский .mcp.json перемещён в ${MBAK##*/} — свои серверы, если были, верни руками"
  else
    echo "loft: .mcp.json оставлен как есть — проверь, нужны ли его серверы этому проекту (каждый стоит токенов схем в каждой сессии)"
  fi
fi

# Остатки прежних систем: только детект — уборка это работа скилла
# migrate-specos (карантин с манифестом отката, по решению владельца).
if report="$(cd "$DEST" && CLAUDE_PROJECT_DIR="$DEST" bash .claude/skills/migrate-specos/sweep.sh 2>/dev/null)"; then
  case "$report" in
    *"MACHINERY (0)"*)
      echo "loft: остатков прежних систем не найдено" ;;
    *)
      echo "loft: обнаружена машинерия specos/skillforge — ничего не перенесено."
      echo "loft: в Claude Code запусти скилл migrate-specos (превью: bash .claude/skills/migrate-specos/sweep.sh)" ;;
  esac
fi

# Самопроверка установки: рухнуть здесь лучше, чем молча отдать битое ядро.
selfcheck_fail() { echo "loft: САМОПРОВЕРКА ПРОВАЛЕНА — $1" >&2; exit 1; }
[ -f "$DEST/.claude/CLAUDE.md" ] || selfcheck_fail "нет контракта"
[ -x "$DEST/.claude/hooks/leak-guard.sh" ] && [ -x "$DEST/.claude/hooks/update-check.sh" ] \
  || selfcheck_fail "хуки не исполняемые"
[ "$(ls "$DEST/.claude/skills" | wc -l | tr -d ' ')" -ge 14 ] || selfcheck_fail "скиллов меньше 14"
( cd "$DEST" && python3 .claude/skills/link-check/scripts/link_check.py spec >/dev/null 2>&1 ) \
  || selfcheck_fail "link_check не отрабатывает"
echo "loft: самопроверка установки — OK"

echo "loft $(cat "$SRC/VERSION") установлен в $DEST"
case "$SRC" in
  "$DEST"/*) echo "loft: каталог loft/ можно оставить для обновлений (повторный запуск скрипта) или удалить; добавь loft/ в .gitignore" ;;
esac
echo "далее: открой проект в Claude Code; конвертеру нужны pandoc и python3+lxml (только для ingest-*)"
