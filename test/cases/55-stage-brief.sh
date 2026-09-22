# Самотесты loft — 55-stage-brief. Хук SessionStart(resume|compact): одна строка
# только при открытой стадии (brief.md без report.md), иначе молчание.

section "stage-brief — напоминание об открытой стадии"
SB="$TMP/sb"; mkdir -p "$SB"
out="$(cd "$SB" && CLAUDE_PROJECT_DIR="$SB" bash "$HK/stage-brief.sh" 2>&1)"
[ -z "$out" ] && ok || bad "без stages/ хук молчит (got: $out)"
mkdir -p "$SB/stages/001-alpha" "$SB/stages/002-beta"
echo "бриф" > "$SB/stages/001-alpha/brief.md"; echo "бриф" > "$SB/stages/002-beta/brief.md"; echo "отчёт" > "$SB/stages/002-beta/report.md"
out="$(cd "$SB" && CLAUDE_PROJECT_DIR="$SB" bash "$HK/stage-brief.sh" 2>&1)"
has "stages/001-alpha/brief.md" "$out" "открытая стадия названа"
hasnt "002-beta" "$out" "закрытая стадия не упомянута"
[ "$(printf '%s' "$out" | wc -l | tr -d ' ')" -le 1 ] && ok || bad "хук печатает одну строку"
echo "отчёт" > "$SB/stages/001-alpha/report.md"
out="$(cd "$SB" && CLAUDE_PROJECT_DIR="$SB" bash "$HK/stage-brief.sh" 2>&1)"
[ -z "$out" ] && ok || bad "все стадии закрыты — хук молчит"
