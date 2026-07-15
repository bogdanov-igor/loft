#!/usr/bin/env bash
# SessionStart: сказать владельцу, что существует более новый loft.
#
# Контракт: печатаем ОДНУ строку и только когда обновление реально есть.
# Всё, что печатает хук, попадает в контекст модели каждую сессию, поэтому
# молчание — путь по умолчанию, и счастливый путь стоит ноль токенов.
# Источники: локальные папки ядра (loft/ в проекте, $LOFT_HOME) и релизы
# GitHub (кэш 24ч, потолок 3с — медленная сеть не задерживает старт).
# Ни один сбой не блокирует сессию — все ошибки выходят молча с кодом 0.
set -uo pipefail
[ "${LOFT_NO_UPDATE_CHECK:-0}" = "1" ] && exit 0
PROJECT="${CLAUDE_PROJECT_DIR:-$PWD}"

LOCAL_FILE="$PROJECT/.claude/VERSION"
[ -f "$LOCAL_FILE" ] || exit 0
LOCAL="$(tr -d '[:space:]' < "$LOCAL_FILE")"
[ -n "$LOCAL" ] || exit 0

# Числовое semver-сравнение: $1 строго новее $2?
newer() {
  local a="$1" b="$2" i ai bi
  local -a A B
  IFS=. read -r -a A <<< "${a%%-*}"
  IFS=. read -r -a B <<< "${b%%-*}"
  for i in 0 1 2; do
    ai="${A[i]:-0}"; bi="${B[i]:-0}"
    case "$ai$bi" in *[!0-9]*) return 1 ;; esac
    [ "$ai" -gt "$bi" ] && return 0
    [ "$ai" -lt "$bi" ] && return 1
  done
  return 1
}

best=""
consider() {
  local v="$1"
  [ -n "$v" ] || return 0
  if [ -z "$best" ] || newer "$v" "$best"; then best="$v"; fi
}

# Локальные источники: папка loft/ в проекте (tgz могли обновить, а install
# забыть) и репо ядра, если задан $LOFT_HOME.
for src in "$PROJECT/loft/VERSION" "${LOFT_HOME:+$LOFT_HOME/VERSION}"; do
  [ -n "$src" ] && [ -f "$src" ] && consider "$(tr -d '[:space:]' < "$src")"
done

# GitHub releases: latest tag, кэш суточный.
REPO="${LOFT_UPDATE_REPO:-bogdanov-igor/loft}"
CACHE_DIR="${XDG_CACHE_HOME:-$HOME/.cache}/loft"
CACHE="$CACHE_DIR/latest-${REPO//\//-}"
if mkdir -p "$CACHE_DIR" 2>/dev/null; then
  now="$(date +%s)"; fresh=0
  if [ -f "$CACHE" ]; then
    ts="$(sed -n 1p "$CACHE" 2>/dev/null)"
    case "$ts" in ''|*[!0-9]*) ts=0 ;; esac
    [ $(( now - ts )) -lt 86400 ] && fresh=1
  fi
  if [ "$fresh" -eq 1 ]; then
    REMOTE="$(sed -n 2p "$CACHE" 2>/dev/null)"
  else
    REMOTE="$(curl -fsSL -m 3 \
      -H 'Accept: application/vnd.github+json' \
      "https://api.github.com/repos/$REPO/releases/latest" 2>/dev/null \
      | sed -n 's/.*"tag_name"[[:space:]]*:[[:space:]]*"v\{0,1\}\([^"]*\)".*/\1/p' | head -1)"
    [ -n "$REMOTE" ] && printf '%s\n%s\n' "$now" "$REMOTE" > "$CACHE" 2>/dev/null
  fi
  consider "${REMOTE:-}"
fi

[ -n "$best" ] || exit 0
if newer "$best" "$LOCAL"; then
  printf 'loft: доступна версия %s (установлена %s). Обновление: свежий tgz из github.com/%s/releases → `bash loft/install.sh` из корня проекта — ядро заменится, состояние проекта не тронется. Скажи владельцу один раз и продолжай.\n' \
    "$best" "$LOCAL" "$REPO"
fi
exit 0
