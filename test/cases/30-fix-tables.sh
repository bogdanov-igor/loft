# Самотесты loft — 30-fix-tables. Подключается из test/run.sh; переменные REPO/SK/HK/TMP
# и функции ok/bad/has/hasnt/section приходят оттуда.

FT="$SK/ingest-confluence/scripts/fix_tables.py"

# ── fix_tables: конверсия + идемпотентность + защита verbatim-кода ──────────
section "fix_tables — идемпотентность и защита кода"
F="$TMP/ft"; mkdir -p "$F"
cat > "$F/p.md" <<'EOF'
---
title: Страница
confluence_id: 1
space: OB
---
до
<table class="confluenceTable"><tr><th>А</th></tr><tr><td>Б</td></tr></table>
после
```
<table><tr><td>в фенсе — не трогать</td></tr></table>
<a href="https://x.example/f" class="fence-x">якорь в фенсе</a>
<a href="../attachments/1_2.pdf" data-linked-resource-default-alias="Ф.pdf"></a>
<img src="https://j.example/secure/viewavatar?fence"/>
state -\> фенс
**▸ Нажмите здесь для раскрытия...**
**BATCH\**
```

Отступный блок кода:

    <table><tr><td>в отступе — не трогать</td></tr></table>
    <a href="https://y.example/i" class="indent-x">якорь в отступе</a>
    <a href="../attachments/1_2.pdf" data-linked-resource-default-alias="И.pdf"></a>
    <img src="https://j.example/secure/viewavatar?indent"/>
    state -\> отступ
    **▸ Нажмите здесь для раскрытия...**

хвост
EOF
python3 "$FT" "$F" >/dev/null 2>&1
c1="$(cat "$F/p.md")"
has "| А |" "$c1" "HTML-таблица стала GFM"
has "<table><tr><td>в фенсе — не трогать</td></tr></table>" "$c1" "таблица в фенсе осталась HTML"
has "<table><tr><td>в отступе — не трогать</td></tr></table>" "$c1" "таблица в отступном коде осталась HTML"
has 'class="fence-x"' "$c1" "якорь в фенсе не тронут"
has 'class="indent-x"' "$c1" "якорь в отступном коде не тронут"
has "viewavatar?fence" "$c1" "иконка в фенсе не выпилена"
has "viewavatar?indent" "$c1" "иконка в отступном коде не выпилена"
has 'data-linked-resource-default-alias="Ф.pdf"></a>' "$c1" "пустой якорь в фенсе не получил текст"
has 'data-linked-resource-default-alias="И.pdf"></a>' "$c1" "пустой якорь в отступном коде не получил текст"
has "state -\\> фенс" "$c1" "стрелка в фенсе не разэкранирована"
has "state -\\> отступ" "$c1" "стрелка в отступном коде не разэкранирована"
hasnt "**▸ Подробнее**" "$c1" "плейсхолдер в verbatim-коде не заменён"
has "**BATCH\\**" "$c1" "битый болд в фенсе не «починен»"
out="$(python3 "$FT" "$F" 2>&1)"
has "0/1 files changed" "$out" "второй прогон — ноль изменений"

# ── fix_tables: чистка якорей, jira-иконки, скраб атрибутов ─────────────────
section "fix_tables — якоря и атрибутный шлак"
F2="$TMP/ft2"; mkdir -p "$F2"
cat > "$F2/a.md" <<'EOF'
---
title: Якоря
confluence_id: 2
space: OB
---
Интро <a href="https://x.example/y" class="external-link" rel="nofollow">док</a> и <a href="../attachments/1_2.pdf" class="confluence-embedded-file" draggable="false">SV.pdf</a> и <a href="%D0%A1%D0%98-1.md">Регистрация</a>.
Болд-ссылка: <a href="../СИ-2.md" rel="nofollow"><strong>Жирная</strong></a>
Джира: <a href="https://jira.example/browse/OB-1?src=confmacro" class="jira-issue-key"><img src="https://jira.example/secure/viewavatar?size=xsmall"/>OB-1</a>
Сам-себе-текст: <a href="https://conf.example/pages/viewpage.action?pageId=9" class="external-link">https://conf.example/pages/viewpage.action?pageId=9</a>
<table class="confluenceTable" style="width: 100.0%;"><tbody><tr><td colspan="2" class="confluenceTd" style="text-align: center;"><a href="z.md" class="k" data-y="1">внутри</a></td></tr></tbody></table>
Код не трогать: `<a href="x" class="y">код</a>`, экранированный \<b\> тоже.
EOF
cp "$F2/a.md" "$F2/.a.orig"; mv "$F2/.a.orig" "$TMP/a.orig"
python3 "$FT" "$F2" >/dev/null 2>&1
a="$(cat "$F2/a.md")"
has "[док](https://x.example/y)" "$a" "внешний якорь стал markdown-ссылкой"
has "[[1_2.pdf|SV.pdf]]" "$a" "якорь-вложение стал wikilink"
has "[[СИ-1|Регистрация]]" "$a" "внутренний якорь стал wikilink (unquote)"
has "[[СИ-2|Жирная]]" "$a" "болд внутри якоря срезан до плейн-алиаса"
has "[OB-1](https://jira.example/browse/OB-1?src=confmacro)" "$a" "jira-якорь стал markdown"
hasnt "viewavatar" "$a" "jira-аватарка выпилена"
has "<https://conf.example/pages/viewpage.action?pageId=9>" "$a" "текст==href -> автолинк"
has '<td colspan="2"><a href="z.md">внутри</a></td>' "$a" "в таблице: атрибуты вычищены, colspan цел"
has '`<a href="x" class="y">код</a>`' "$a" "инлайн-код не тронут"
has 'экранированный \<b\>' "$a" "экранированный литерал не тронут"
hasnt 'class="external-link"' "$a" "атрибутного шлака не осталось (кроме инлайн-кода)"
hasnt 'confluenceTable' "$a" "конфлюенс-классы таблиц вычищены"
out="$(python3 "$FT" "$F2" 2>&1)"
has "0/1 files changed" "$out" "чистка якорей идемпотентна"
F3="$TMP/ft3"; mkdir -p "$F3"; cp "$TMP/a.orig" "$F3/a.md"
python3 "$FT" "$F3" --expand-spans >/dev/null 2>&1
a3="$(cat "$F3/a.md")"
has '| [[z\|внутри]] |  |' "$a3" "expand-spans: colspan-таблица развёрнута, ссылка — wikilink"
hasnt "<table" "$a3" "expand-spans: HTML-таблиц не осталось"
out="$(python3 "$FT" "$F3" --expand-spans 2>&1)"
has "0/1 files changed" "$out" "expand-spans идемпотентен"

# ── fix_tables: ремонт артефактов + pagemap-резолюция ───────────────────────
section "fix_tables — артефакты pandoc и pagemap"
F4="$TMP/ft4"; mkdir -p "$F4"
cat > "$F4/.pagemap.json" <<'EOF'
{"9": {"basename": "Стр-9", "relpath": "dir/Стр-9.md"},
 "104": {"basename": "Тини-104", "relpath": "Тини-104.md"}}
EOF
cat > "$F4/r.md" <<'EOF'
---
title: Артефакты
confluence_id: 500
space: OB
---
1. Обновить таблицу **BATCH_TASKS\**
- KrakendLatencyP\*\*
3. Тип **KrakendPercentIncorrectResponse** или **KrakendLatencyP\*\***
Поле `state` -\> `active` и code --\> done, в коде не трогать: `a -\> b`
**▸ Нажмите здесь для раскрытия...**
| Jira | [!OB-455](https://jira.example.uz/browse/OB-455?src=confmacro) - тикет |
Ссылка [https://conf.example/pages/viewpage.action?pageId=9](https://conf.example/pages/viewpage.action?pageId=9) и автолинк <https://conf.example/x/aA>
<table><tbody><tr><td colspan="2"><a href="https://conf.example/pages/viewpage.action?pageId=9">в таблице</a></td>
<td colspan="3">вторая строка</td></tr></tbody></table>
EOF
python3 "$FT" "$F4" >/dev/null 2>&1
r4="$(cat "$F4/r.md")"
has '**BATCH_TASKS**' "$r4" "битый болд **X\\** починен"
has 'KrakendLatencyP\*\*'"$(printf '\n')" "$r4$(printf '\n')" "легитимный escape \\*\\* не тронут"
has '**KrakendLatencyP\*\***' "$r4" "легитимный escape в болде не тронут"
has '`state` -> `active` и code --> done' "$r4" "стрелки разэкранированы"
has '`a -\> b`' "$r4" "стрелка в инлайн-коде не тронута"
has "**▸ Подробнее**" "$r4" "плейсхолдер expand заменён"
has "[OB-455](https://jira.example.uz/browse/OB-455?src=confmacro)" "$r4" "[!KEY] потерял лишний !"
has "[[Стр-9]]" "$r4" "md-ссылка с pageId стала wikilink без URL-алиаса"
has "[[Тини-104]]" "$r4" "автолинк /x/ tiny резолвится через pagemap"
has 'href="dir/%D0%A1%D1%82%D1%80-9.md"' "$r4" "в таблице: conf-href локализован в относительный путь"
grep -q '<table><tbody><tr><td colspan="2">.*вторая строка.*</table>' "$F4/r.md" \
  && ok || bad "многострочный fallback-блок схлопнут в одну строку"
out="$(python3 "$FT" "$F4" 2>&1)"
has "0/1 files changed" "$out" "ремонт артефактов идемпотентен"

# ── fix_tables: рукописные слои под wiki/ ──────────────────────────────────
# По умолчанию трогаются только страницы с confluence_id: рукописные слои
# (_KNOWLEDGE-MAP.md, _TRAINING/, _specs/) переписываться не должны.
section "fix_tables — рукописные слои без confluence_id"
F5="$TMP/ft5"; mkdir -p "$F5"
cat > "$F5/page-7.md" <<'EOF'
---
title: Стр
confluence_id: 7
space: OB
---
<table><tr><th>А</th></tr><tr><td>Б</td></tr></table>
EOF
cat > "$F5/_NOTES.md" <<'EOF'
# Рукопись

Ссылка за корень wiki: [профиль](../spec/_STRUCTURE.md)

<table><tr><th>В</th></tr><tr><td>Г</td></tr></table>
EOF
sum1="$(cksum < "$F5/_NOTES.md")"
out="$(python3 "$FT" "$F5" 2>&1)"
sum2="$(cksum < "$F5/_NOTES.md")"
[ "$sum1" = "$sum2" ] && ok || bad "рукописный файл без confluence_id не тронут"
has "[skip] 1 file(s) without confluence_id" "$out" "пропуск рукописных слоёв виден в отчёте"
has "1/1 files changed" "$out" "в знаменателе только страницы с confluence_id"
has "| А |" "$(cat "$F5/page-7.md")" "страница с confluence_id обработана"
out="$(python3 "$FT" "$F5" --all 2>&1)"
n="$(cat "$F5/_NOTES.md")"
has "| В |" "$n" "--all: рукописный файл обработан по требованию"
has "[профиль](../spec/_STRUCTURE.md)" "$n" "ссылка за корень wiki осталась markdown, а не wikilink по имени"

# ── fix_tables: футер «Источник» — ссылка на живую страницу ─────────────────
# Прошлая версия резолвила URL футера по pagemap и получала самоссылку:
# единственный указатель на живой Confluence терялся.
section "fix_tables — футер «Источник»"
F6="$TMP/ft6"; mkdir -p "$F6/dir"
cat > "$F6/.pagemap.json" <<'EOF'
{"501": {"basename": "Стр-501", "relpath": "dir/Стр-501.md"},
 "502": {"basename": "Стр-502", "relpath": "Стр-502.md"}}
EOF
cat > "$F6/.space.json" <<'EOF'
{"key": "OB", "name": "Спейс", "base_url": "https://conf.example", "snapshot": "2026-01-01", "pages": 2}
EOF
cat > "$F6/dir/Стр-501.md" <<'EOF'
---
title: Стр 501
confluence_id: 501
source: https://conf.example/pages/viewpage.action?pageId=501
space: OB
---

# Стр 501

Ссылка на себя: [эта страница](https://conf.example/pages/viewpage.action?pageId=501)
Ссылка на соседа: [сосед](https://conf.example/pages/viewpage.action?pageId=502)
Якорь на себя: <a href="https://conf.example/pages/viewpage.action?pageId=501" class="external-link">сюда</a>

---

**Родитель:** [[Стр-502|Стр 502]]  
**Источник:** [[Стр-501|Confluence OB / 501]]
EOF
cat > "$F6/Стр-502.md" <<'EOF'
---
title: Стр 502
confluence_id: 502
space: OB
---

# Стр 502

**Источник:** [[Стр-502|Confluence OB / 502]]
EOF
python3 "$FT" "$F6" >/dev/null 2>&1
s1="$(cat "$F6/dir/Стр-501.md")"; s2="$(cat "$F6/Стр-502.md")"
has "**Источник:** [Confluence OB / 501](https://conf.example/pages/viewpage.action?pageId=501)" "$s1" \
  "футер восстановлен из frontmatter source:"
has "**Источник:** [Confluence OB / 502](https://conf.example/pages/viewpage.action?pageId=502)" "$s2" \
  "футер восстановлен из base_url .space.json"
has "[эта страница](https://conf.example/pages/viewpage.action?pageId=501)" "$s1" \
  "ссылка на себя в потоке осталась URL Confluence"
has "[сюда](https://conf.example/pages/viewpage.action?pageId=501)" "$s1" \
  "якорь на себя стал markdown с URL, а не самоссылкой"
has "[[Стр-502|сосед]]" "$s1" "ссылка на соседнюю страницу по-прежнему резолвится в wikilink"
hasnt "Источник:** [[" "$s1" "самоссылок в футере не осталось"
out="$(python3 "$FT" "$F6" 2>&1)"
has "0/2 files changed" "$out" "восстановленный футер идемпотентен"

# ── fix_tables: ошибки не роняют прогон ────────────────────────────────────
section "fix_tables — ошибки, коды возврата, битый pagemap"
F7="$TMP/ft7"; mkdir -p "$F7"
cat > "$F7/good-8.md" <<'EOF'
---
title: Хорошая
confluence_id: 8
space: OB
---
<table><tr><th>А</th></tr><tr><td>Б</td></tr></table>
EOF
python3 -c "open('$F7/bad-9.md','wb').write(b'---\ntitle: bad\nconfluence_id: 9\nspace: OB\n---\n\xff\xfe binary\n')"
printf '{ битый json' > "$F7/.pagemap.json"
out="$(python3 "$FT" "$F7" 2>&1)"; rc=$?
[ "$rc" -eq 1 ] && ok || bad "страница с ошибкой -> rc=1 (получено $rc)"
has "[error] bad-9.md" "$out" "битая страница названа в логе"
has "[warn] .pagemap.json unreadable" "$out" "битый pagemap — предупреждение, а не падение"
has "| А |" "$(cat "$F7/good-8.md")" "соседняя страница обработана, прогон не упал"
out="$(python3 "$FT" "$TMP/нет-такого-пути" 2>&1)"; rc=$?
[ "$rc" -eq 2 ] && ok || bad "несуществующий путь -> rc=2 (получено $rc)"
has "path not found" "$out" "несуществующий путь назван"

# ── fix_tables: «<table» в прозе и две таблицы в строке ─────────────────────
section "fix_tables — прозаический <table> и inline-таблицы"
F8="$TMP/ft8"; mkdir -p "$F8"
cat > "$F8/t-10.md" <<'EOF'
---
title: Проза
confluence_id: 10
space: OB
---
Тег <table> задаёт таблицу, пример `<table class="x">`, экранированный \<table\> — текст.

После прозы якорь обязан стать ссылкой: <a href="https://x.example/y" class="external-link">док</a>

<table><tr><th>А</th></tr><tr><td>Б</td></tr></table><table><tr><th>В</th></tr><tr><td>Г</td></tr></table>

Текст перед таблицей <table><tr><td>инлайн</td></tr></table>
EOF
out="$(python3 "$FT" "$F8" 2>&1)"
t8="$(cat "$F8/t-10.md")"
has "[док](https://x.example/y)" "$t8" "упоминание <table> в прозе не переводит файл в режим «только скраб»"
has 'пример `<table class="x">`' "$t8" "<table> в инлайн-коде не тронут"
has 'экранированный \<table\>' "$t8" "экранированный \\<table\\> не тронут"
has "| А |" "$t8" "первая из двух таблиц в строке сконвертирована"
has "| В |" "$t8" "вторая таблица той же строки сконвертирована тем же прогоном"
has "inline-table" "$out" "таблица не с начала строки записана в fallback-лог"
out="$(python3 "$FT" "$F8" 2>&1)"
has "0/1 files changed" "$out" "две таблицы в строке — идемпотентно за один прогон"

# ── fix_tables: скраб атрибутов без кавычек и якоря-имена ───────────────────
section "fix_tables — атрибуты без кавычек, <a name>"
F9="$TMP/ft9"; mkdir -p "$F9"
cat > "$F9/t-11.md" <<'EOF'
---
title: Атрибуты
confluence_id: 11
space: OB
---
Без кавычек: <a href=https://x.example/z class=external>без кавычек</a>
Якорь-имя: <a name="раздел-1" class="anchor" id="a1"></a> Раздел 1
Пустой в коде: `<a href="../attachments/1_2.pdf"></a>`, экранированный \<a href="q"\>\</a\>
Картинка: <img src=https://j.example/secure/viewavatar?size=xsmall />
Оставшийся HTML: <td class="confluenceTd" data-x="1" href=z.md>ячейка</td>
EOF
python3 "$FT" "$F9" >/dev/null 2>&1
t9="$(cat "$F9/t-11.md")"
has "[без кавычек](https://x.example/z)" "$t9" "href без кавычек понят, а не потерян"
has '<a name="раздел-1" id="a1"></a>' "$t9" "<a name>/<a id> пережили скраб (цель #якоря)"
has '`<a href="../attachments/1_2.pdf"></a>`' "$t9" "пустой якорь в инлайн-коде не получил текст"
has 'экранированный \<a href="q"\>\</a\>' "$t9" "экранированный пустой якорь не тронут"
hasnt "viewavatar" "$t9" "иконка с src без кавычек выпилена"
hasnt 'data-x="1"' "$t9" "атрибутный шлак вычищен и в тегах без кавычек"
out="$(python3 "$FT" "$F9" 2>&1)"
has "0/1 files changed" "$out" "скраб атрибутов идемпотентен"

# ── fix_tables: markdown и вложения внутри HTML-таблицы ─────────────────────
section "fix_tables — markdown в <td> и вложения в таблице"
F10="$TMP/ft10"; mkdir -p "$F10"
cat > "$F10/t-12.md" <<'EOF'
---
title: Таблица
confluence_id: 12
space: OB
---
<table class="confluenceTable"><tbody><tr><th>Файл</th><th>Готовый markdown</th></tr>
<tr><td><a href="../attachments/23_45.xlsx" class="confluence-embedded-file">Справочник (2).xlsx</a></td>
<td>[[СИ-1|Регистрация]], **важно** и `код`</td></tr>
<tr><td>обычный текст_с_ [скобками]</td><td>ещё</td></tr></tbody></table>
EOF
python3 "$FT" "$F10" >/dev/null 2>&1
t10="$(cat "$F10/t-12.md")"
has '[[23_45.xlsx\|Справочник (2).xlsx]]' "$t10" "вложение в сконвертированной таблице стало [[файл|имя]]"
has '[[СИ-1\|Регистрация]], **важно** и `код`' "$t10" "готовый markdown в <td> не превратился в мусор"
has '\[скобками\]' "$t10" "ячейка без markdown экранируется как раньше"
out="$(python3 "$FT" "$F10" 2>&1)"
has "0/1 files changed" "$out" "конверсия таблицы с markdown идемпотентна"

# ── fix_tables: одиночный файл в подкаталоге + честный счётчик ──────────────
section "fix_tables — одиночный файл и счётчик wikilinks"
F11="$TMP/ft11"; mkdir -p "$F11/sub"
cat > "$F11/.pagemap.json" <<'EOF'
{"601": {"basename": "Цель-601", "relpath": "Цель-601.md"}}
EOF
cat > "$F11/sub/one-13.md" <<'EOF'
---
title: Один
confluence_id: 13
space: OB
---
Ссылка: [цель](https://conf.example/pages/viewpage.action?pageId=601)

Счётчик: [[Цель-601]], сам на себя [[one-13]], экранированный \[\[не-ссылка\]\]

```
[[в фенсе]]
```
EOF
out="$(python3 "$FT" "$F11/sub/one-13.md" 2>&1)"
has "[pagemap] 1 pages known" "$out" "одиночный файл в подкаталоге нашёл .pagemap.json"
has "[[Цель-601|цель]]" "$(cat "$F11/sub/one-13.md")" "ссылка резолвится в режиме одиночного файла"
has "[wikilinks] 1 -> 2" "$out" "счётчик без фенсов, экранированных и самоссылок"

# ── fix_tables: сырые <img> — embed вместо невидимого HTML ──────────────────
# Старая wiki несёт <img src alt width height>: pandoc оставляет такую картинку
# сырым HTML, невидимым и для link-check, и для Obsidian. convert.py 2.1 снимает
# размер и отдаёт ![[embed]] — постпроцессор обязан давать тот же вывод.
section "fix_tables — сырые картинки"
F13="$TMP/ft13"; mkdir -p "$F13"
cat > "$F13/i-15.md" <<'EOF'
---
title: Картинки
confluence_id: 15
space: OB
---
Локальная: <img src="../assets/123_456.png" alt="diagram (1).png" width="680" height="250"/>
Percent-имя: <img src="../assets/%D0%A4%D0%B0%D0%B9%D0%BB.png" alt="Ф"/>
Внешняя: <img src="https://ext.example/a b.png" alt="Внешняя [x]" width="30"/>
Иконка: <img src="https://j.example/secure/viewavatar?size=xsmall"/>

```
<img src="../assets/999.png" alt="в фенсе" width="10"/>
```

<table><tr><td colspan="2"><img src="../assets/777.png" alt="в таблице" width="10"/></td><td colspan="3">хвост</td></tr></table>
EOF
python3 "$FT" "$F13" >/dev/null 2>&1
i13="$(cat "$F13/i-15.md")"
has "Локальная: ![[123_456.png]]" "$i13" "локальная картинка с размерами стала embed"
has "Percent-имя: ![[Файл.png]]" "$i13" "percent-имя раскодировано в имя embed'а"
has '![Внешняя \[x\]](https://ext.example/a%20b.png)' "$i13" "внешняя картинка стала md-картинкой"
hasnt 'width="680"' "$i13" "размер локальной картинки не пережил конверсию"
hasnt "viewavatar" "$i13" "иконка по-прежнему выпилена раньше конверсии"
has '<img src="../assets/999.png" alt="в фенсе" width="10"/>' "$i13" "картинка в фенсе не тронута"
has '<img src="../assets/777.png" alt="в таблице"/>' "$i13" "в fallback-таблице картинка осталась HTML (без размера)"
out="$(python3 "$FT" "$F13" 2>&1)"
has "0/1 files changed" "$out" "конверсия картинок идемпотентна"

# ── fix_tables: картинки в сконвертированной таблице ───────────────────────
# tablemd отдаёт ячейку с ![alt](путь); в потоке и у convert.py локальная
# картинка — ![[embed]]. Ячейка обязана выглядеть так же, иначе картинки из
# таблиц невидимы для link-check и Obsidian.
section "fix_tables — картинки в ячейках таблиц"
F14="$TMP/ft14"; mkdir -p "$F14"
cat > "$F14/i-16.md" <<'EOF'
---
title: Картинки в таблицах
confluence_id: 16
space: OB
---
<table class="confluenceTable"><tbody><tr><th>Что</th><th>Картинка</th></tr>
<tr><td>локальная</td><td><img src="../assets/123_456.png" alt="схема|альт.png" width="680"/></td></tr>
<tr><td>percent</td><td><img src="../assets/%D0%A4%D0%B0%D0%B9%D0%BB.png" alt="Ф"/></td></tr>
<tr><td>внешняя</td><td><img src="https://ext.example/a b.png" alt="Внешняя [x]"/></td></tr>
</tbody></table>

<table><tr><td colspan="2"><img src="../assets/777.png" alt="в fallback" width="10"/></td><td colspan="3">хвост</td></tr></table>
EOF
python3 "$FT" "$F14" >/dev/null 2>&1
i14="$(cat "$F14/i-16.md")"
has "| локальная | ![[123_456.png]] |" "$i14" "локальная картинка в ячейке стала embed, как у convert.py"
has "| percent | ![[Файл.png]] |" "$i14" "percent-имя в ячейке раскодировано"
hasnt '![[123_456.png\|' "$i14" "у embed'а нет алиаса — экранированный \| не нужен"
has '| внешняя | ![Внешняя \[x\]](https://ext.example/a%20b.png) |' "$i14" "внешняя картинка осталась md-картинкой"
has '<img src="../assets/777.png" alt="в fallback"/>' "$i14" "в fallback-таблице картинка осталась HTML"
out="$(python3 "$FT" "$F14" 2>&1)"
has "0/1 files changed" "$out" "картинки в ячейках — идемпотентно"

# ── fix_tables: --dry-run ничего не пишет ───────────────────────────────────
section "fix_tables — --dry-run"
F12="$TMP/ft12"; mkdir -p "$F12"
cat > "$F12/d-14.md" <<'EOF'
---
title: Черновой прогон
confluence_id: 14
space: OB
---
<table><tr><th>А</th></tr><tr><td>Б</td></tr></table>
EOF
sum1="$(cksum < "$F12/d-14.md")"
out="$(python3 "$FT" "$F12" --dry-run 2>&1)"
sum2="$(cksum < "$F12/d-14.md")"
[ "$sum1" = "$sum2" ] && ok || bad "--dry-run не пишет в файлы"
has "(dry-run)" "$out" "--dry-run помечен в отчёте"
has "1/1 files changed" "$out" "--dry-run считает, что изменилось бы"

# ── fix_tables: свежий вывод convert.py — no-op ─────────────────────────────
if command -v pandoc >/dev/null 2>&1 && python3 -c 'import lxml' 2>/dev/null; then
section "fix_tables — свежий вывод convert.py не трогается"
CW="$TMP/ftconv"
python3 "$SK/ingest-confluence/scripts/convert.py" "$REPO/test/fixtures/export-v2" "$CW/wiki" \
  --base-url https://conf.example >/dev/null 2>&1
out="$(python3 "$FT" "$CW/wiki" 2>&1)"
has "[done] 0/" "$out" "постпроцессор не меняет свежий вывод конвертера"
grep -rq 'Источник:\*\* \[Confluence' "$CW/wiki" && ok || bad "футер конвертера ведёт на Confluence"
grep -rq 'Источник:\*\* \[\[' "$CW/wiki" && bad "футер превратился в самоссылку" || ok
else
section "fix_tables — no-op на выводе convert.py ПРОПУЩЕНО (нет pandoc/lxml)"
fi

# ── fix_tables: неизвестный флаг — rc=2, как у остальных скриптов ───────────
section "fix_tables — неизвестный флаг"
FU="$TMP/fu"; mkdir -p "$FU"; echo "# x" > "$FU/a.md"
out="$(python3 "$SK/ingest-confluence/scripts/fix_tables.py" "$FU" --no-such-flag 2>&1)"; rc=$?
[ "$rc" -eq 2 ] && ok || bad "неизвестный флаг → rc=2 (got $rc)"
has "unknown flag" "$out" "неизвестный флаг назван в сообщении"

# ── fix_tables: цвет конвертера 2.5 переживает чистку атрибутов ─────────────
section "fix_tables — цвет переживает чистку"
FC="$TMP/ftc"; mkdir -p "$FC"
cat > "$FC/p.md" <<'EOF'
---
title: Страница
confluence_id: 1
space: OB
---
Поле <span style="color:#1f845a">x</span> и шлак <span style="color: red; font-weight: bold" class="c">y</span>.
<table class="confluenceTable"><tr><th>А</th></tr><tr><td style="background-color:#ffebe6" class="confluenceTd">да</td></tr></table>
EOF
python3 "$FT" "$FC" >/dev/null 2>&1
fc="$(cat "$FC/p.md")"
has 'Поле <span style="color:#1f845a">x</span> и шлак <span>y</span>.' "$fc" "канонический style остался, стиль Confluence снят"
has '| <span style="background-color:#ffebe6">да</span> |' "$fc" "подсветка ячейки сырой таблицы дошла до GFM"
python3 "$FT" "$FC" >/dev/null 2>&1
[ "$(cat "$FC/p.md")" = "$fc" ] && ok || bad "повторный прогон идемпотентен на цвете"
