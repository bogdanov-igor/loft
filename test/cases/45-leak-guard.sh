# Самотесты loft — 45-leak-guard. Подключается из test/run.sh; переменные REPO/SK/HK/TMP
# и функции ok/bad/has/hasnt/section приходят оттуда.

# ── leak-guard: блокируем только запись значения секрета ────────────────────
section "leak-guard — утечка секретов в запись"
LG="$TMP/lg"; mkdir -p "$LG"
lg() { CLAUDE_PROJECT_DIR="$LG" bash "$HK/leak-guard.sh" 2>&1; }

# Молчание без .secrets.env: хук спит, пока секретов нет.
lg_out="$(printf '%s' '{"tool_name":"Write","tool_input":{"content":"sk-super-secret-value"}}' | lg)"
[ "$lg_out" = "{}" ] && ok || bad "без .secrets.env хук молчит (got: $lg_out)"

{
  printf 'TOKEN=sk-super-secret-value\n'
  printf 'PORT=8080\n'
  printf 'export CRLFKEY=crlf-value-long\r\n'
  printf '%s\n' 'Q=abc"def\ghi'
  printf '%s\n' '  CMT=commentvalue # хвост строки'
  printf '%s\n' 'WEIRD"KEY=weird-value-123'
} > "$LG/.secrets.env"

lg_out="$(printf '%s' '{"tool_name":"Write","tool_input":{"file_path":"a.md","content":"хост: sk-super-secret-value"}}' | lg)"
has '"permissionDecision":"deny"' "$lg_out" "секрет в Write.content — deny"
has 'secret TOKEN' "$lg_out" "в отказе назван ключ"

lg_out="$(printf '%s' '{"tool_name":"Write","tool_input":{"file_path":"a.md","content":"обычный текст"}}' | lg)"
[ "$lg_out" = "{}" ] && ok || bad "чистая запись проходит (got: $lg_out)"

# Значение с кавычкой и бэкслешем приезжает в payload JSON-экранированным.
lg_out="$(printf '%s' '{"tool_name":"Write","tool_input":{"file_path":"a.md","content":"v=abc\"def\\ghi"}}' | lg)"
has 'secret Q' "$lg_out" "JSON-экранированное значение распознано"

# Правка, УБИРАЮЩАЯ утёкший секрет: значение только в old_string.
lg_out="$(printf '%s' '{"tool_name":"Edit","tool_input":{"file_path":"a.md","old_string":"TOKEN=sk-super-secret-value","new_string":"TOKEN={{secret:TOKEN}}"}}' | lg)"
[ "$lg_out" = "{}" ] && ok || bad "Edit, убирающий секрет, разрешён (got: $lg_out)"
lg_out="$(printf '%s' '{"tool_name":"Edit","tool_input":{"file_path":"a.md","old_string":"x","new_string":"sk-super-secret-value"}}' | lg)"
has '"deny"' "$lg_out" "Edit, вносящий секрет, — deny"

# Короткие значения секретами не считаются: иначе PORT=8080 ловит любое число.
lg_out="$(printf '%s' '{"tool_name":"Write","tool_input":{"file_path":"a.md","content":"слушает порт 8080"}}' | lg)"
[ "$lg_out" = "{}" ] && ok || bad "короткое значение не секрет (got: $lg_out)"

# Терпимый разбор .secrets.env: export, CRLF, инлайн-комментарий.
lg_out="$(printf '%s' '{"tool_name":"Write","tool_input":{"file_path":"a.md","content":"crlf-value-long"}}' | lg)"
has 'secret CRLFKEY' "$lg_out" "export KEY= и CRLF разобраны"
lg_out="$(printf '%s' '{"tool_name":"Write","tool_input":{"file_path":"a.md","content":"commentvalue"}}' | lg)"
has 'secret CMT' "$lg_out" "инлайн-комментарий не попал в значение"

# Ключ с кавычкой не должен ломать JSON ответа — иначе харнесс не поймёт отказ.
lg_out="$(printf '%s' '{"tool_name":"Write","tool_input":{"file_path":"a.md","content":"weird-value-123"}}' | lg)"
printf '%s' "$lg_out" | python3 -c 'import json,sys; d=json.load(sys.stdin); sys.exit(0 if d["hookSpecificOutput"]["permissionDecision"]=="deny" else 1)' \
  && ok || bad "JSON ответа валиден при ключе с кавычкой (got: $lg_out)"
