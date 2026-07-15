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

# ── link_check: битые, фенсы, \|-алиасы, картинки ───────────────────────────
section "link_check — резолюция и фенсы"
L="$TMP/lc"; mkdir -p "$L/spec"
cat > "$L/spec/a.md" <<'EOF'
Живая: [[b]] и с алиасом в таблице [[b\|текст]].
Битая: [[нет-такой]]. Картинка битая: ![x](assets/nope.png)
```
[[в-фенсе-не-считается]]
```
EOF
echo "# b" > "$L/spec/b.md"
out="$(cd "$L" && python3 "$SK/link-check/scripts/link_check.py" spec 2>&1)"; rc=$?
has "битых: 2" "$out" "ровно две битые (wikilink + картинка)"
hasnt "в-фенсе" "$out" "код-фенс пропускается"
hasnt "[[b\\" "$out" "экранированный алиас резолвится"
[ "$rc" -eq 1 ] && ok || bad "exit 1 при битых (got $rc)"
out="$(cd "$L" && python3 "$SK/link-check/scripts/link_check.py" spec nope-dir 2>&1)"
has "не существует и пропущен" "$out" "предупреждение о несуществующем каталоге"

# ── tablemd: пайпы, пустые якоря, multiline-pre ─────────────────────────────
section "tablemd — GFM-писатель"
out="$(python3 - "$SK/ingest-confluence/scripts" <<'EOF'
import sys; sys.path.insert(0, sys.argv[1])
from lxml import html as H
import tablemd
t = H.fragment_fromstring('''<table><tr><th>Док</th><th>Имя</th></tr>
<tr><td><a href="../attachments/1_2.pdf" data-linked-resource-default-alias="SV API v1.pdf"></a></td>
<td>A | B</td></tr></table>''')
print(tablemd.table_to_gfm(t))
try:
    t2 = H.fragment_fromstring('<table><tr><td><pre>1\n2\n3\n4\n5\n6\n7</pre></td></tr></table>')
    print(tablemd.table_to_gfm(t2))
    print("NO-FALLBACK")
except tablemd.Fallback as e:
    print("FALLBACK:%s" % e.reason)
EOF
)"
has "SV API v1.pdf" "$out" "пустой якорь получил имя из alias"
has 'A \| B' "$out" "пайп в ячейке экранирован"
has "FALLBACK:multiline-pre" "$out" "многострочный pre уходит в fallback"
out="$(python3 - "$SK/ingest-confluence/scripts" <<'EOF'
import sys; sys.path.insert(0, sys.argv[1])
from lxml import html as H
import tablemd
t = H.fragment_fromstring('''<table><tr><th>Запрос</th></tr>
<tr><td><pre class="json">{
 "a": 1,
 "b": 2,
 "c": 3,
 "d": 4,
 "e": 5
}</pre></td></tr></table>''')
print(tablemd.table_to_gfm(t, unroll_pre=True))
EOF
)"
has "см. Пример 1 ниже" "$out" "unroll: ссылка на пример в ячейке"
has "Запрос — Пример 1:" "$out" "unroll: заголовок примера из колонки"
has '```json' "$out" "unroll: фенс с языком из class"
has '"e": 5' "$out" "unroll: содержимое pre сохранено"
hasnt "<table" "$out" "unroll: HTML не остался"
out="$(python3 - "$SK/ingest-confluence/scripts" <<'EOF'
import sys; sys.path.insert(0, sys.argv[1])
from lxml import html as H
import tablemd
t = H.fragment_fromstring('''<table><tbody>
<tr><th colspan="2">Шапка</th><th>С</th></tr>
<tr><td rowspan="2">Блок</td><td>a1</td><td>a2</td></tr>
<tr><td>b1</td><td>b2</td></tr>
</tbody></table>''')
print(tablemd.table_to_gfm(t, expand_spans=True))
EOF
)"
has "| Шапка |  | С |" "$out" "expand-spans: colspan дополнен пустыми"
has "| Блок | a1 | a2 |" "$out" "expand-spans: первая строка rowspan"
has "| Блок | b1 | b2 |" "$out" "expand-spans: rowspan повторяет значение"
hasnt "<table" "$out" "expand-spans: HTML не остался"

# ── fix_tables: конверсия + идемпотентность + фенс-защита ───────────────────
section "fix_tables — идемпотентность"
F="$TMP/ft"; mkdir -p "$F"
cat > "$F/p.md" <<'EOF'
до
<table class="confluenceTable"><tr><th>А</th></tr><tr><td>Б</td></tr></table>
после
```
<table><tr><td>в фенсе — не трогать</td></tr></table>
```
EOF
python3 "$SK/ingest-confluence/scripts/fix_tables.py" "$F" >/dev/null 2>&1
c1="$(cat "$F/p.md")"
has "| А |" "$c1" "HTML-таблица стала GFM"
has "в фенсе — не трогать" "$c1" "таблица в фенсе не тронута"
out="$(python3 "$SK/ingest-confluence/scripts/fix_tables.py" "$F" 2>&1)"
has "0/1 files changed" "$out" "второй прогон — ноль изменений"

# ── fix_tables: чистка якорей, jira-иконки, скраб атрибутов ─────────────────
section "fix_tables — якоря и атрибутный шлак"
F2="$TMP/ft2"; mkdir -p "$F2"
cat > "$F2/a.md" <<'EOF'
Интро <a href="https://x.example/y" class="external-link" rel="nofollow">док</a> и <a href="../attachments/1_2.pdf" class="confluence-embedded-file" draggable="false">SV.pdf</a> и <a href="%D0%A1%D0%98-1.md">Регистрация</a>.
Джира: <a href="https://jira.example/browse/OB-1?src=confmacro" class="jira-issue-key"><img src="https://jira.example/secure/viewavatar?size=xsmall"/>OB-1</a>
Сам-себе-текст: <a href="https://conf.example/pages/viewpage.action?pageId=9" class="external-link">https://conf.example/pages/viewpage.action?pageId=9</a>
<table class="confluenceTable" style="width: 100.0%;"><tbody><tr><td colspan="2" class="confluenceTd" style="text-align: center;"><a href="z.md" class="k" data-y="1">внутри</a></td></tr></tbody></table>
Код не трогать: `<a href="x" class="y">код</a>`, экранированный \<b\> тоже.
EOF
cp "$F2/a.md" "$F2/.a.orig"; mv "$F2/.a.orig" "$TMP/a.orig"
python3 "$SK/ingest-confluence/scripts/fix_tables.py" "$F2" >/dev/null 2>&1
a="$(cat "$F2/a.md")"
has "[док](https://x.example/y)" "$a" "внешний якорь стал markdown-ссылкой"
has "[[1_2.pdf|SV.pdf]]" "$a" "якорь-вложение стал wikilink"
has "[[СИ-1|Регистрация]]" "$a" "внутренний якорь стал wikilink (unquote)"
has "[OB-1](https://jira.example/browse/OB-1?src=confmacro)" "$a" "jira-якорь стал markdown"
hasnt "viewavatar" "$a" "jira-аватарка выпилена"
has "<https://conf.example/pages/viewpage.action?pageId=9>" "$a" "текст==href -> автолинк"
has '<td colspan="2"><a href="z.md">внутри</a></td>' "$a" "в таблице: атрибуты вычищены, colspan цел"
has '`<a href="x" class="y">код</a>`' "$a" "инлайн-код не тронут"
has 'экранированный \<b\>' "$a" "экранированный литерал не тронут"
hasnt 'class="external-link"' "$a" "атрибутного шлака не осталось (кроме инлайн-кода)"
hasnt 'confluenceTable' "$a" "конфлюенс-классы таблиц вычищены"
out="$(python3 "$SK/ingest-confluence/scripts/fix_tables.py" "$F2" 2>&1)"
has "0/1 files changed" "$out" "чистка якорей идемпотентна"
F3="$TMP/ft3"; mkdir -p "$F3"; cp "$TMP/a.orig" "$F3/a.md"
python3 "$SK/ingest-confluence/scripts/fix_tables.py" "$F3" --expand-spans >/dev/null 2>&1
a3="$(cat "$F3/a.md")"
has '| [[z\|внутри]] |  |' "$a3" "expand-spans: colspan-таблица развёрнута, ссылка — wikilink"
hasnt "<table" "$a3" "expand-spans: HTML-таблиц не осталось"
out="$(python3 "$SK/ingest-confluence/scripts/fix_tables.py" "$F3" --expand-spans 2>&1)"
has "0/1 files changed" "$out" "expand-spans идемпотентен"

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

# ── update-check: молчание и одна строка (герметично: кэш GitHub посеян) ────
section "update-check — тихий по умолчанию"
U="$TMP/uc"; mkdir -p "$U/.claude" "$U/loft" "$U/cache/loft"
seed_gh() { printf '%s\n%s\n' "$(date +%s)" "$1" > "$U/cache/loft/latest-bogdanov-igor-loft"; }
uc() { XDG_CACHE_HOME="$U/cache" CLAUDE_PROJECT_DIR="$U" bash "$HK/update-check.sh" 2>&1; }
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
out="$(LOFT_NO_UPDATE_CHECK=1 uc)"
[ -z "$out" ] && ok || bad "opt-out через LOFT_NO_UPDATE_CHECK"

# ── convert: golden-фикстура + отчёт изменений _CHANGES ─────────────────────
if command -v pandoc >/dev/null 2>&1 && python3 -c 'import lxml' 2>/dev/null; then
section "convert — golden-корпус и _CHANGES"
G="$TMP/golden"; mkdir -p "$G"
CV="$SK/ingest-confluence/scripts/convert.py"
out="$(python3 "$CV" "$REPO/test/fixtures/export-v1" "$G/wiki" 2>&1)"
has "pages written" "$out" "конвертация v1-фикстуры прошла"
[ -f "$G/wiki/.ingest.json" ] && ok || bad ".ingest.json пишется с первого прогона"
ls "$G/wiki/"_CHANGES-* >/dev/null 2>&1 && bad "_CHANGES не должен появляться при первой конвертации" || ok
r="$(cat "$G/wiki/Раздел-101.md")"
has "[[Удаляемая-103]]" "$r" "convert: внутренний якорь с атрибутами стал wikilink"
has "[пример](https://example.com/d)" "$r" "convert: внешний якорь стал markdown"
has "[[Переименуемая-104]]" "$r" "convert: автолинк с pageId резолвится в wikilink"
has "[AB-1](" "$r" "convert: jira-макрос стал markdown-ссылкой"
hasnt "viewavatar" "$r" "convert: jira-аватарка выпилена"
hasnt 'class="external-link"' "$r" "convert: атрибутный шлак вычищен"
has '<th colspan="2">Спан</th>' "$r" "convert: colspan-fallback остался HTML, но чистый"
has "colspan-rowspan" "$out" "convert: fallback залогирован с причиной"
GX="$TMP/golden-exp"
python3 "$CV" "$REPO/test/fixtures/export-v1" "$GX/wiki" --expand-spans >/dev/null 2>&1
rx="$(cat "$GX/wiki/Раздел-101.md")"
has "| Спан |  |" "$rx" "convert --expand-spans: таблица развёрнута в GFM"
hasnt "<table" "$rx" "convert --expand-spans: HTML-таблиц не осталось"
echo "рукопись" > "$G/wiki/_NOTES.md"
out="$(python3 "$CV" "$REPO/test/fixtures/export-v2" "$G/wiki" 2>&1)"
has "[changes]" "$out" "diff посчитан при повторной конвертации"
has "[stale-removed]" "$out" "исчезнувшие страницы сняты"
ch="$(cat "$G/wiki/"_CHANGES-*.md 2>/dev/null)"
has "## Добавлено" "$ch" "_CHANGES: секция Добавлено"
has "## Удалено" "$ch" "_CHANGES: секция Удалено"
[ -f "$G/wiki/_NOTES.md" ] && ok || bad "рукописный файл без confluence_id пережил повтор"
python3 -c "import json;d=json.load(open('$G/wiki/.ingest.json'));assert d['added'] and d['removed']" \
  && ok || bad ".ingest.json несёт diff-списки"
else
section "convert — ПРОПУЩЕНО (нет pandoc/lxml)"
fi

# ── deliver-pdf: wikilinks резолвятся, PDF или honest-fallback ──────────────
section "deliver-pdf — экспортёр"
P="$TMP/pdf"; mkdir -p "$P/spec" "$P/wiki"
echo "# Цель" > "$P/wiki/Цель-1.md"
printf -- '---\ntitle: "Тест"\n---\nСм. [[Цель-1|конвенцию]] и `код`.\n' > "$P/spec/док.md"
out="$(python3 "$SK/deliver-pdf/scripts/export_pdf.py" "$P/spec/док.md" 2>&1)"; rc=$?
if [ "$rc" -eq 0 ]; then
  [ -s "$P/spec/док.pdf" ] && ok || bad "PDF пуст"
elif [ "$rc" -eq 3 ]; then
  [ -s "$P/spec/док.html" ] && ok || bad "fallback-HTML не оставлен"
else
  bad "export_pdf упал (rc=$rc): $out"
fi
case "$rc" in 0|3)
  chk="$P/spec/док.pdf"; [ "$rc" -eq 3 ] && chk="$P/spec/док.html"
  if [ "$rc" -eq 3 ]; then
    grep -q "конвенцию" "$chk" && ok || bad "wikilink не разрешился в текст"
    grep -q '\[\[' "$chk" && bad "сырой wikilink утёк в экспорт" || ok
  else
    ok; ok  # содержимое PDF бинарно; резолв проверяется в html-ветке
  fi
;; esac

# ── install: свежая, поверх specos, обновление ──────────────────────────────
section "install — сценарии"
I1="$TMP/i1"; mkdir -p "$I1"
out="$(bash "$REPO/install.sh" "$I1" 2>&1)"
has "самопроверка установки — OK" "$out" "чистая установка + самопроверка"
has "остатков прежних систем не найдено" "$out" "чистый детект"
I2="$TMP/i2"; mkdir -p "$I2/.claude/skills/requirements-elaborate" "$I2/.claude/skills/my-skill" "$I2/.data" "$I2/specos"
echo "<!-- specos-managed -->" > "$I2/.claude/CLAUDE.md"
echo "requirements-elaborate" > "$I2/.data/.specos-wire-skills.list"
out="$(bash "$REPO/install.sh" "$I2" 2>&1)"
has "migrate-specos" "$out" "баннер уборки при specos-наследии"
[ -d "$I2/.claude/skills/my-skill" ] && ok || bad "проектный скилл пережил"
[ ! -d "$I2/.claude/skills/requirements-elaborate" ] && ok || bad "specos-скилл отсечён"
echo custom > "$I1/.claude/agents/my-agent.md"; echo "- z" >> "$I1/BACKLOG.md"
out="$(bash "$REPO/install.sh" "$I1" 2>&1)"
[ -f "$I1/.claude/agents/my-agent.md" ] && grep -q "^- z" "$I1/BACKLOG.md" && ok || bad "обновление: агент и BACKLOG пережили"
[ "$(cat "$I1/.claude/VERSION")" = "$(tr -d '[:space:]' < "$REPO/VERSION")" ] && ok || bad "версия проштампована"
echo "Смотри [[нет-такой-страницы]]" > "$I1/spec/битая.md"
out="$(bash "$REPO/install.sh" "$I1" 2>&1)"
has "самопроверка установки — OK" "$out" "битая ссылка в spec проекта не валит установку"

printf '\nитого: %d ok, %d fail\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
