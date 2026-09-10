#!/usr/bin/env bash
# Самотесты ядра loft: гоняют поставляемые скрипты на одноразовых фикстурах.
#
#   bash test/run.sh
#
# Каждый кейс — либо реальный баг, пойманный руками (в т.ч. верификацией
# 2026-07-15), либо свойство, обещанное документацией. Это релизный гейт
# build-archive.sh. Оффлайн, во временных каталогах, наружу не пишет.
set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd -P)"
SK="$REPO/bundle/.claude/skills"
HK="$REPO/bundle/.claude/hooks"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT

pass=0; fail=0
ok()  { pass=$((pass+1)); }
bad() { fail=$((fail+1)); printf '  FAIL: %s\n' "$1"; }
has()   { case "$2" in *"$1"*) ok ;; *) bad "$3 (нет: $1)" ;; esac; }
hasnt() { case "$2" in *"$1"*) bad "$3 (лишнее: $1)" ;; *) ok ;; esac; }
section(){ printf '• %s\n' "$1"; }

# Кейсы — по файлу на зону, в порядке имён; каждый подключается в эту же
# оболочку, поэтому счётчики и временный каталог общие.
for case in "$REPO/test/cases"/*.sh; do
  . "$case"
done

printf '\nитого: %d ok, %d fail\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
