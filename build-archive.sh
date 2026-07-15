#!/usr/bin/env bash
# Сборка дистрибутива: dist/loft_<version>.tgz + .sha256 рядом.
# Архив распаковывается в одну папку loft/; в проекте:
#   tar -xzf loft_<version>.tgz && bash loft/install.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd -P)"
VER="$(tr -d '[:space:]' < "$ROOT/VERSION")"
OUT="$ROOT/dist"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

# Релизный гейт: самотесты ядра до любой упаковки.
bash "$ROOT/test/run.sh" >/dev/null || { echo "loft: test/run.sh ПРОВАЛЕН — сборка отменена" >&2; exit 1; }

mkdir -p "$STAGE/loft" "$OUT"
# Доки и лицензия едут внутри архива: получатель tgz получает полный
# мануал на двух языках оффлайн, не заходя в репо.
cp "$ROOT/README.md" "$ROOT/README.ru.md" "$ROOT/LICENSE" "$ROOT/NOTICE" \
   "$ROOT/CHANGELOG.md" "$ROOT/VERSION" "$ROOT/install.sh" "$STAGE/loft/"
cp -R "$ROOT/bundle" "$STAGE/loft/bundle"
cp -R "$ROOT/docs" "$STAGE/loft/docs"
find "$STAGE" -name '.DS_Store' -delete
chmod +x "$STAGE/loft/install.sh"
find "$STAGE/loft/bundle" -name '*.sh' -exec chmod +x {} +

TGZ="$OUT/loft_${VER}.tgz"
tar -czf "$TGZ" -C "$STAGE" loft
( cd "$OUT" && shasum -a 256 "loft_${VER}.tgz" > "loft_${VER}.tgz.sha256" )

# Самотест: распаковать во временный каталог и реально установить.
T="$(mktemp -d)"
( cd "$T" && tar -xzf "$TGZ" && bash loft/install.sh >/dev/null )
fail() { echo "loft: самотест архива ПРОВАЛЕН — $1 (площадка сохранена: $T)" >&2; exit 1; }
[ -f "$T/.claude/CLAUDE.md" ]                        || fail "нет контракта"
[ -f "$T/BACKLOG.md" ] && [ -f "$T/QUESTIONS.md" ]   || fail "сиды не посеяны"
[ -f "$T/memory/MEMORY.md" ]                         || fail "нет индекса памяти"
[ -d "$T/spec" ] && [ -d "$T/inbox" ]                || fail "нет каталогов корпуса"
[ -x "$T/.claude/hooks/leak-guard.sh" ] && [ -x "$T/.claude/hooks/update-check.sh" ] \
                                                     || fail "хуки не исполняемые"
[ -x "$T/.claude/skills/migrate-specos/sweep.sh" ]   || fail "sweep не исполняемый"
[ "$(cat "$T/.claude/VERSION")" = "$VER" ]           || fail "версия не проштампована"
[ "$(ls "$T/.claude/skills" | wc -l | tr -d ' ')" -ge 13 ] || fail "скиллов меньше 13"
out="$(cd "$T" && CLAUDE_PROJECT_DIR="$T" bash .claude/hooks/update-check.sh 2>/dev/null || true)"
case "$out" in *"доступна версия"*) fail "update-check шумит на собственной версии" ;; esac
[ -f "$T/.claude/skills/ingest-confluence/scripts/convert.py" ] || fail "нет конвертера"
[ -f "$T/.claude/skills/ingest-confluence/scripts/fix_tables.py" ] || fail "нет постпроцессора таблиц"
# Инструменты обязаны работать со свежей установки, не только из репо.
( cd "$T" && python3 .claude/skills/link-check/scripts/link_check.py spec >/dev/null ) \
  || fail "link_check не отрабатывает на свежей установке"
( cd "$T" && python3 -c "import sys; sys.path.insert(0,'.claude/skills/ingest-confluence/scripts'); import tablemd" ) \
  || fail "tablemd не импортируется"
[ -f "$T/loft/LICENSE" ] && [ -f "$T/loft/README.ru.md" ] \
  && [ -f "$T/loft/docs/ru/why-loft.md" ] && [ -f "$T/loft/docs/en/why-loft.md" ] \
  || fail "доки/лицензия не уехали в архив"
rm -rf "$T"

echo "собрано: $TGZ"
echo "         ${TGZ}.sha256"
echo "получатель проверяет: shasum -c loft_${VER}.tgz.sha256  (рядом с tgz)"
