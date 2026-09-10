# Самотесты loft — 40-sweep. Подключается из test/run.sh; переменные REPO/SK/HK/TMP
# и функции ok/bad/has/hasnt/section приходят оттуда.

# ── sweep: детект, карантин, неприкосновенность состояния ───────────────────
section "migrate-specos sweep — карантин машинерии"
S="$TMP/sw"; mkdir -p "$S/specos" "$S/.data" "$S/wiki" "$S/spec"
touch "$S/specos-0.8.1.tar.gz" "$S/.data/.specos-version" "$S/.data/runs.jsonl"
echo x > "$S/wiki/страница.md"; echo y > "$S/spec/тз.md"; echo "# B" > "$S/BACKLOG.md"
out="$(CLAUDE_PROJECT_DIR="$S" bash "$SK/migrate-specos/sweep.sh" 2>&1)"
has "MACHINERY (4)" "$out" "детект нашёл 4 объекта"
[ -d "$S/specos" ] && ok || bad "детект-режим ничего не переносит"
out="$(CLAUDE_PROJECT_DIR="$S" bash "$SK/migrate-specos/sweep.sh" --apply 2>&1)"
has "перенесено: 4" "$out" "карантин перенёс 4"
[ ! -d "$S/specos" ] && ok || bad "specos/ уехал"
[ -f "$S/wiki/страница.md" ] && [ -f "$S/spec/тз.md" ] && ok || bad "состояние не тронуто"
m="$(ls "$S/.loft-migration")" && [ -f "$S/.loft-migration/$m/MANIFEST.md" ] && ok || bad "манифест существует"
grep -q "src:migrate-specos" "$S/BACKLOG.md" && ok || bad "строка ре-аудита в BACKLOG"
out="$(CLAUDE_PROJECT_DIR="$S" bash "$SK/migrate-specos/sweep.sh" 2>&1)"
has "MACHINERY (0)" "$out" "после карантина чисто"

# Формат строки очереди — как в сиде BACKLOG (`- P1 | …`), без чекбокса.
grep -q '^- P1 | ' "$S/BACKLOG.md" && ok || bad "строка ре-аудита в формате сида"
hasnt "- [ ] P1" "$(cat "$S/BACKLOG.md")" "чекбокса в строке нет"

# Откат по манифесту работает и когда родительский каталог уже убрали.
mfst="$S/.loft-migration/$m/MANIFEST.md"
cmd="$(grep -F 'было: .data/runs.jsonl' "$mfst" | sed -e 's/^- `//' -e 's/`.*$//')"
rm -rf "$S/.data"
( cd "$S" && eval "$cmd" ) >/dev/null 2>&1
[ -f "$S/.data/runs.jsonl" ] && ok || bad "откат по манифесту при удалённом родителе (cmd: $cmd)"
rm -f "$S/.data/runs.jsonl"

# Бэкапы .claude: чужой помечается, свой (от переустановки loft) — нет.
mkdir -p "$S/.claude.bak.20260101000000" "$S/.claude.bak.20260102000000"
echo "1.2.0" > "$S/.claude.bak.20260101000000/VERSION"
echo "# чужое" > "$S/.claude.bak.20260102000000/CLAUDE.md"
out="$(CLAUDE_PROJECT_DIR="$S" bash "$SK/migrate-specos/sweep.sh" 2>&1)"
hasnt ".claude.bak.20260101000000" "$out" "свой бэкап loft не помечен"
has ".claude.bak.20260102000000" "$out" "чужой бэкап помечен"
echo "<!-- specos-managed -->" > "$S/.claude.bak.20260101000000/CLAUDE.md"
out="$(CLAUDE_PROJECT_DIR="$S" bash "$SK/migrate-specos/sweep.sh" 2>&1)"
has ".claude.bak.20260101000000" "$out" "бэкап с маркером specos помечен даже с VERSION"

# .mcp.json помечается той же эвристикой, что разбирает install.sh: сам сервер
# specos'овский (имя или компонент пути), а не слово specos где-то в строке.
printf '%s\n' '{"mcpServers":{"specos-memory":{"command":"node","args":["/opt/specos/mcp/memory.js"]}}}' > "$S/.mcp.json"
out="$(CLAUDE_PROJECT_DIR="$S" bash "$SK/migrate-specos/sweep.sh" 2>&1)"
has ".mcp.json — всё ещё содержит specos-серверы" "$out" "specos-сервер в .mcp.json помечен"
printf '%s\n' '{"mcpServers":{"serena":{"command":"uvx","args":["--from","/opt/tools/serena-specos-fork/bin/serena-mcp"],"env":{"NOTE":"мигрировано со specos"}}}}' > "$S/.mcp.json"
out="$(CLAUDE_PROJECT_DIR="$S" bash "$SK/migrate-specos/sweep.sh" 2>&1)"
hasnt ".mcp.json" "$out" "чужой сервер с упоминанием specos в пути не помечен"
printf '%s' 'не json вовсе' > "$S/.mcp.json"
out="$(CLAUDE_PROJECT_DIR="$S" bash "$SK/migrate-specos/sweep.sh" 2>&1)"
has ".mcp.json — не разобран" "$out" "битый .mcp.json помечен как неразобранный"
rm -f "$S/.mcp.json"
