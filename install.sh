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
  # Имя бэкапа уникально: два запуска в одну секунду иначе вкладывают новый
  # бэкап внутрь старого (mv в существующий каталог), и прежний .claude
  # оказывается на два уровня глубже, чем сказано в сообщении.
  BAKBASE="$DEST/.claude.bak.$(date +%Y%m%d%H%M%S)"
  BAK="$BAKBASE"; n=2
  while [ -e "$BAK" ]; do BAK="$BAKBASE-$n"; n=$((n+1)); done
  mv "$DEST/.claude" "$BAK"
  echo "loft: прежний .claude перемещён в ${BAK##*/}"
fi
cp -R "$SRC/bundle/.claude" "$DEST/.claude"
tr -d '[:space:]' < "$SRC/VERSION" > "$DEST/.claude/VERSION"
find "$DEST/.claude" -name "*.sh" -exec chmod +x {} +

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

# Пользовательская настройка Claude Code переживает переустановку: разрешения
# (settings.local.json), свои команды и правила, свои output-styles. Ядро их не
# поставляет — кроме output-styles/analyst.md, поэтому переносим пофайлово, а не
# каталогом. specos-овские commands/rules проектными не считаем: они остаются в
# бэкапе вместе с остальной машинерией.
restored_cfg=""
if [ -n "${BAK:-}" ]; then
  if [ -f "$BAK/settings.local.json" ] && [ ! -f "$DEST/.claude/settings.local.json" ]; then
    cp "$BAK/settings.local.json" "$DEST/.claude/settings.local.json"
    restored_cfg="$restored_cfg settings.local.json"
  fi
  if [ "$SPECOS_PREV" -eq 0 ]; then
    for d in commands rules; do
      [ -d "$BAK/$d" ] && [ ! -e "$DEST/.claude/$d" ] || continue
      cp -R "$BAK/$d" "$DEST/.claude/$d"
      restored_cfg="$restored_cfg $d/"
    done
  fi
  if [ -d "$BAK/output-styles" ]; then
    mkdir -p "$DEST/.claude/output-styles"
    for f in "$BAK/output-styles"/*; do
      [ -f "$f" ] || continue
      name="$(basename "$f")"
      [ -e "$DEST/.claude/output-styles/$name" ] && continue
      cp "$f" "$DEST/.claude/output-styles/$name"
      restored_cfg="$restored_cfg output-styles/$name"
    done
  fi
  [ -n "$restored_cfg" ] && echo "loft: перенесена пользовательская настройка:$restored_cfg"
fi

# Сиды: создаём только отсутствующее — состояние проекта не перезаписывается.
mkdir -p "$DEST/memory/lessons" "$DEST/memory/antipatterns" \
         "$DEST/memory/patterns" "$DEST/memory/structures" \
         "$DEST/stages" "$DEST/spec" "$DEST/spec/_reference" "$DEST/spec/_reviews" \
         "$DEST/inbox" "$DEST/inbox/done"
for d in memory/lessons memory/antipatterns memory/patterns memory/structures \
         stages spec spec/_reference spec/_reviews inbox inbox/done; do
  touch "$DEST/$d/.gitkeep"
done
for f in BACKLOG.md QUESTIONS.md; do
  [ -f "$DEST/$f" ] || cp "$SRC/bundle/seed/$f" "$DEST/$f"
done
[ -f "$DEST/memory/MEMORY.md" ] || cp "$SRC/bundle/seed/MEMORY.md" "$DEST/memory/MEMORY.md"
# Профиль документации: голос с умолчаниями ядра, структуру заполняет владелец.
[ -f "$DEST/spec/_STRUCTURE.md" ] || cp "$SRC/bundle/seed/_STRUCTURE.md" "$DEST/spec/_STRUCTURE.md"

# Секреты — вне git (правило 8 контракта). Файл без завершающего перевода
# строки — обычное дело; дописать в него вслепую значит склеить последний
# паттерн со своим и испортить оба.
touch "$DEST/.gitignore"
if [ -s "$DEST/.gitignore" ] && [ -n "$(tail -c 1 "$DEST/.gitignore")" ]; then
  printf '\n' >> "$DEST/.gitignore"
fi
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
#
# specos'овским считается конфиг, где сам сервер specos'овский: имя сервера со
# словом specos или путь запуска с компонентом specos (specos/, .specos/,
# specos-0.8/). Грепа по слову мало — «мигрировано со specos» в комментарии или
# в env уводило в бэкап чужой рабочий конфиг. Не разобрали JSON — не трогаем.
mcp_kind() {
  python3 - "$1" <<'PY' 2>/dev/null
import json, sys
try:
    d = json.load(open(sys.argv[1], encoding="utf-8"))
except Exception:
    sys.exit(2)
srv = d.get("mcpServers")
if not isinstance(srv, dict):
    sys.exit(2)

def specos_path(value):
    for comp in str(value).replace("\\", "/").split("/"):
        c = comp.lower()
        if c in ("specos", ".specos") or c.startswith(("specos-", "specos_", "specos.")):
            return True
    return False

for name, cfg in srv.items():
    if "specos" in str(name).lower():
        print("specos"); sys.exit(0)
    values = []
    if isinstance(cfg, dict):
        for key in ("command", "cwd", "url"):
            if cfg.get(key) is not None:
                values.append(cfg[key])
        args = cfg.get("args")
        if isinstance(args, list):
            values += args
        env = cfg.get("env")
        if isinstance(env, dict):
            values += list(env.keys())
    else:
        values.append(cfg)
    for v in values:
        if specos_path(v):
            print("specos"); sys.exit(0)
print("other")
PY
}
if [ -f "$DEST/.mcp.json" ]; then
  MCPKIND="$(mcp_kind "$DEST/.mcp.json" || true)"
  case "$MCPKIND" in
    specos)
      MBAKBASE="$DEST/.mcp.json.bak.$(date +%Y%m%d%H%M%S)"
      MBAK="$MBAKBASE"; n=2
      while [ -e "$MBAK" ]; do MBAK="$MBAKBASE-$n"; n=$((n+1)); done
      mv "$DEST/.mcp.json" "$MBAK"
      echo "loft: specos'овский .mcp.json перемещён в ${MBAK##*/} — свои серверы, если были, верни руками" ;;
    other)
      echo "loft: .mcp.json оставлен как есть — проверь, нужны ли его серверы этому проекту (каждый стоит токенов схем в каждой сессии)" ;;
    *)
      echo "loft: .mcp.json не разобрался (битый JSON или нестандартная схема) — оставлен как есть; если это конфиг specos, убери его руками" ;;
  esac
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
# Рухнув, откатываемся: полуустановленное ядро на месте рабочего — худшее из
# состояний, а владелец не обязан помнить, как называется бэкап.
selfcheck_fail() {
  echo "loft: САМОПРОВЕРКА ПРОВАЛЕНА — $1" >&2
  if [ -n "${BAK:-}" ] && [ -d "$BAK" ]; then
    rm -rf "$DEST/.claude"
    mv "$BAK" "$DEST/.claude"
    echo "loft: установка откачена — прежний .claude вернулся на место из ${BAK##*/}" >&2
  else
    echo "loft: прежнего .claude не было; неудачная установка осталась в $DEST/.claude — удали каталог перед повторной попыткой" >&2
  fi
  exit 1
}
[ -f "$DEST/.claude/CLAUDE.md" ] || selfcheck_fail "нет контракта"
[ -x "$DEST/.claude/hooks/leak-guard.sh" ] && [ -x "$DEST/.claude/hooks/update-check.sh" ] \
  || selfcheck_fail "хуки не исполняемые"
[ "$(ls "$DEST/.claude/skills" | wc -l | tr -d ' ')" -ge 15 ] || selfcheck_fail "скиллов меньше 15"
# проверяем, что скрипт РАБОТАЕТ, на пустой площадке: на живом проекте
# link_check честно выходит с кодом 1 при битых ссылках — это не поломка
SCTMP="$(mktemp -d)"
( cd "$DEST" && python3 .claude/skills/link-check/scripts/link_check.py "$SCTMP" >/dev/null 2>&1 ) \
  || { rmdir "$SCTMP" 2>/dev/null; selfcheck_fail "link_check не отрабатывает"; }
rmdir "$SCTMP" 2>/dev/null
echo "loft: самопроверка установки — OK"

echo "loft $(cat "$SRC/VERSION") установлен в $DEST"
case "$SRC" in
  "$DEST"/*) echo "loft: каталог loft/ можно оставить для обновлений (повторный запуск скрипта) или удалить; добавь loft/ в .gitignore" ;;
esac
echo "далее: открой проект в Claude Code. pandoc нужен ingest-confluence, ingest-docs, review-intake и deliver-pdf; lxml — только ingest-confluence"
