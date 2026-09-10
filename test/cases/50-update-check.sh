# Самотесты loft — 50-update-check. Подключается из test/run.sh; переменные REPO/SK/HK/TMP
# и функции ok/bad/has/hasnt/section приходят оттуда.

# ── update-check: молчание и одна строка (герметично: кэш GitHub посеян) ────
# LOFT_NO_UPDATE_CHECK=0 задаётся явно: сборка выставляет 1 на всё окружение,
# и кейсы обязаны проверять хук, а не унаследованный opt-out.
section "update-check — тихий по умолчанию"
U="$TMP/uc"; mkdir -p "$U/.claude" "$U/loft" "$U/cache/loft"
seed_gh() { printf '%s\n%s\n' "$(date +%s)" "$1" > "$U/cache/loft/latest-bogdanov-igor-loft"; }
uc() { XDG_CACHE_HOME="$U/cache" CLAUDE_PROJECT_DIR="$U" LOFT_NO_UPDATE_CHECK=0 bash "$HK/update-check.sh" 2>&1; }
echo "0.2.0" > "$U/.claude/VERSION"; echo "0.2.0" > "$U/loft/VERSION"; seed_gh "0.1.0"
out="$(uc)"
[ -z "$out" ] && ok || bad "равные версии — молчание (got: $out)"
echo "0.3.0" > "$U/loft/VERSION"
out="$(uc)"
has "доступна версия 0.3.0" "$out" "новая локальная версия объявляется"
echo "0.1.0" > "$U/loft/VERSION"
out="$(uc)"
[ -z "$out" ] && ok || bad "старая папка loft/ — молчание (не даунгрейдим)"
seed_gh "9.9.9"
out="$(uc)"
has "доступна версия 9.9.9" "$out" "GitHub-релиз новее — объявляется (из кэша)"
seed_gh "0.1.0"
out="$(XDG_CACHE_HOME="$U/cache" CLAUDE_PROJECT_DIR="$U" LOFT_NO_UPDATE_CHECK=1 bash "$HK/update-check.sh" 2>&1)"
[ -z "$out" ] && ok || bad "opt-out через LOFT_NO_UPDATE_CHECK"

# ── недоступная сеть не платится тремя секундами каждую сессию ──────────────
# curl подменён заглушкой: без негативного кэша хук дёргал бы её каждый старт.
UN="$TMP/ucn"; mkdir -p "$UN/.claude" "$UN/cache" "$UN/bin"
echo "0.2.0" > "$UN/.claude/VERSION"
printf '#!/bin/sh\necho call >> "%s"\nexit 7\n' "$UN/curl.log" > "$UN/bin/curl"
chmod +x "$UN/bin/curl"; : > "$UN/curl.log"
ucn() { PATH="$UN/bin:$PATH" XDG_CACHE_HOME="$UN/cache" CLAUDE_PROJECT_DIR="$UN" LOFT_NO_UPDATE_CHECK=0 bash "$HK/update-check.sh" 2>&1; }
out="$(ucn)"
[ -z "$out" ] && ok || bad "сеть недоступна — молчание (got: $out)"
[ -f "$UN/cache/loft/latest-bogdanov-igor-loft" ] && ok || bad "неудачный запрос кэшируется"
out="$(ucn)"
[ "$(wc -l < "$UN/curl.log" | tr -d ' ')" = "1" ] && ok || bad "негативный кэш: второй старт не ходит в сеть"

# ── HOME не задан: кэшу негде жить, но хук не падает ────────────────────────
mkdir -p "$UN/loft"; echo "0.9.0" > "$UN/loft/VERSION"
out="$(env -u HOME -u XDG_CACHE_HOME PATH="$UN/bin:$PATH" CLAUDE_PROJECT_DIR="$UN" LOFT_NO_UPDATE_CHECK=0 bash "$HK/update-check.sh" 2>&1)"
hasnt "unbound" "$out" "HOME не задан — не падает"
has "доступна версия 0.9.0" "$out" "HOME не задан — локальный источник работает"
