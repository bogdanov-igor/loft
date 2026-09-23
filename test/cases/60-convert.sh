# Самотесты loft — 60-convert. Подключается из test/run.sh; переменные REPO/SK/HK/TMP
# и функции ok/bad/has/hasnt/section приходят оттуда.

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
has "[[Переименуемая-104|метод]]" "$r" "convert: /spaces/…/pages/<id> резолвится"
has "[[Переименуемая-104|короткая]]" "$r" "convert: tiny-ссылка /x/ декодируется с A-паддингом"
has "**BATCH_TASKS**" "$r" "convert: хвостовой <br> вынесен из болда (не **X\\**)"
hasnt '\**' "$r" "convert: битого закрытия болда нет"
has "**QR_PAYMENTS** по ключу" "$r" "convert: пробел на границе болда вынесен наружу"
has "**вложенный**" "$r" "convert: вложенный strong сплющен"
hasnt "****" "$r" "convert: голых **** нет"
has "state -> active" "$r" "convert: стрелка -> не переэкранирована"
has "code --> done" "$r" "convert: стрелка --> не переэкранирована"
has "▸ Подробнее" "$r" "convert: дефолтный лейбл expand заменён"
hasnt "Нажмите здесь для раскрытия" "$r" "convert: плейсхолдер expand не утёк"
has "неизвестный макрос Confluence" "$r" "convert: unknown-macro оставил маркер, а не молчание"
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
# ── convert: крайние случаи разметки (edge-фикстура) ────────────────────────
section "convert — крайние случаи разметки"
E="$TMP/edge"; mkdir -p "$E"
# --space не передаём: ключ должен приехать из index.html (Key), а не из имени
# каталога — от него зависит, чьи страницы конвертер вправе удалять
out="$(python3 "$CV" "$REPO/test/fixtures/edge" "$E/wiki" 2>&1)"
p1="$(cat "$E/wiki/Панели-и-таблицы-201.md")"
p2="$(cat "$E/wiki/Ссылки-и-картинки-202.md")"
has "space: EDGE" "$p1" "convert: ключ спейса взят из index.html, не из имени каталога"
has "**Заголовок панели**" "$p1" "convert: заголовок info-панели сохранён жирным"
has "хвост после таблицы" "$p1" "convert: текст сразу после </table> не потерян"
has "- | Код | Смысл |" "$p1" "convert: таблица в <li> начинается с маркера списка"
has "  |----|----|" "$p1" "convert: строки таблицы в списке выровнены под маркер"
# фенсы неприкосновенны: ссылка, сущность и одинокий бэкслеш внутри примера
has "см. [док](203.html)" "$p1" "convert: ссылка внутри фенса не переписана в wikilink"
has "сущность &#10; в примере" "$p1" "convert: &#10; внутри фенса не вычищен"
[ "$(grep -c '^\\$' "$E/wiki/Панели-и-таблицы-201.md")" -ge 1 ] \
  && ok || bad "одинокий бэкслеш внутри фенса не съеден"
has "![](https://example.com/pic.png)" "$p2" "convert: внешняя картинка без alt цела"
[ "$(grep -c '^!$' "$E/wiki/Ссылки-и-картинки-202.md")" -eq 0 ] \
  && ok || bad "картинка не схлопнулась в одинокий !"
has "![[202_pic.png]]" "$p2" "convert: картинка с width стала ![[embed]]"
hasnt "<img" "$p2" "convert: сырого <img> не осталось"
has "[[Заглушка-А-203|якорь]]" "$p2" \
  "convert: фрагмент без цели снят, а страница-адресат осталась"
has "![[202_pic.png]] [[Заглушка-Б-204" "$p2" "convert: картинка-ссылка стала embed + wikilink"
has "[link-miss]" "$out" "convert: ссылка на страницу вне выгрузки залогирована"
hasnt "](999.html)" "$p2" "convert: битой ссылки на 999.html не осталось"
python3 -c "import json;d=json.load(open('$E/wiki/.ingest.json'));assert d['missing_links'] and d['missing_links'][0]['target']=='999.html'" \
  && ok || bad ".ingest.json несёт missing_links"
python3 -c "import json;d=json.load(open('$E/wiki/.ingest.json'));assert d['snapshot_date_source']=='footer' and d['converter_version']" \
  && ok || bad ".ingest.json несёт источник даты и версию конвертера"
python3 "$SK/ingest-confluence/scripts/make_index.py" "$E/wiki" >/dev/null 2>&1 \
  && ok || bad "make_index отрабатывает на edge-фикстуре"

# ── convert: якоря-цели и навигация по ним ──────────────────────────────────
# Цель якоря — это ещё не навигация: Obsidian/Foam прыгают по тексту заголовка
# и по block-id (^id), а <a name> для них невидим. Поэтому у якоря три формы
# ссылки по месту, где он стоит: заголовок -> #Текст заголовка, абзац ->
# #^a-<8 hex sha1 имени>, ячейка таблицы -> #id (в ячейке block-id не работает).
section "convert — якоря-цели и навигация по ним"
AN="$TMP/anchor"; cp -R "$REPO/test/fixtures/edge" "$AN"
cat > "$AN/203.html" <<'EOF'
<html><head><meta charset="utf-8"/></head><body><div id="main-content">
<p>Заглушка А.</p>
<p><span class="confluence-anchor-link" id="Раздел-Заголовок"></span>Целевой раздел.</p>
<h2>Ручной <a name="ручной"></a></h2>
<h3><span class="confluence-anchor-link" id="труба"></span>Труба | в заголовке</h3>
<p><span class="confluence-anchor-link" id="дубль-один"></span>Двойной абзац<span class="confluence-anchor-link" id="дубль-два"></span>.</p>
<p>Ссылка и цель разом: <a href="204.html" name="и-цель">Б</a>.</p>
<p>На свой якорь: <a href="#Раздел-Заголовок">сюда</a> и <a href="#ручной">к ручному</a>.</p>
<p>На якорь с трубой: <a href="#труба">к трубе</a>.</p>
<p>На якорь в ячейке: <a href="#в-таблице">в ячейку</a>.</p>
<p>На оба дубля: <a href="#дубль-один">раз</a> и <a href="#дубль-два">два</a>.</p>
<p>На чужой якорь: <a href="#нет-такого">потеряшка</a>.</p>
<p>Абсолютная с фрагментом:
<a href="https://conf.example.com/pages/viewpage.action?pageId=204#раздел-Б">на раздел Б</a>.</p>
<table class="confluenceTable"><tr><th>Ключ</th><th>Смысл</th></tr>
<tr><td><span class="confluence-anchor-link" id="в-таблице"></span>k1</td><td>v1</td></tr></table>
</div></body></html>
EOF
# соседняя страница ссылается на все три вида якорей 203-й: карту якорей
# страницы конвертер обязан знать ДО того, как перепишет ссылки на неё
cat > "$AN/204.html" <<'EOF'
<html><head><meta charset="utf-8"/></head><body><div id="main-content">
<p>Заглушка Б.</p>
<p>На чужой заголовок: <a href="203.html#ручной">к ручному</a>.</p>
<p>На чужой абзац: <a href="203.html#Раздел-Заголовок">к разделу</a>.</p>
<p>На чужую ячейку: <a href="203.html#в-таблице">в ячейку</a>.</p>
</div></body></html>
EOF
out="$(python3 "$CV" "$AN" "$TMP/an/wiki" 2>&1)"
a3="$(cat "$TMP/an/wiki/Заглушка-А-203.md")"
a4="$(cat "$TMP/an/wiki/Заглушка-Б-204.md")"
has '<a name="Раздел-Заголовок"></a>Целевой раздел. ^a-c1fc01f3' "$a3" \
  "convert: якорь-макрос Confluence стал <a name> и block-id в конце абзаца"
has '<a name="ручной"></a>' "$a3" "convert: <a name> из выгрузки пережил чистку атрибутов"
hasnt '## Ручной <a' "$a3" "convert: якорь вынесен из заголовка, текст заголовка чист"
has '<a name="и-цель"></a>[[Заглушка-Б-204|Б]]' "$a3" \
  "convert: ссылка-и-цель разом осталась ссылкой и дала якорь"
has '| <a name="в-таблице"></a>k1 |' "$a3" "convert: якорь в ячейке пережил сборку GFM-таблицы"
hasnt '| <a name="в-таблице"></a>k1 ^a-' "$a3" "convert: block-id в ячейку не приписан"
# ── три формы ссылки на якорь ───────────────────────────────────────────────
# якорь в абзаце: block-id ^a-<8 hex sha1 имени> — единственное, по чему
# Obsidian прыгает внутрь абзаца. sha1("Раздел-Заголовок")[:8] = c1fc01f3
has "[[#^a-c1fc01f3|сюда]]" "$a3" "convert: ссылка на якорь в абзаце — по block-id"
has "[[Заглушка-А-203#^a-c1fc01f3|якорь]]" "$(cat "$TMP/an/wiki/Ссылки-и-картинки-202.md")" \
  "convert: ссылка с чужой страницы на якорь в абзаце — по block-id"
has "[[Заглушка-А-203#^a-c1fc01f3|к разделу]]" "$a4" \
  "convert: карта якорей чужой страницы известна до переписывания ссылок"
# якорь в заголовке: ссылка идёт по тексту заголовка, а сам <a name> остаётся
# строкой перед ним — по нему резолвит HTML/PDF-экспорт
has "[[#Ручной|к ручному]]" "$a3" "convert: ссылка на якорь в заголовке — по тексту заголовка"
has "[[Заглушка-А-203#Ручной|к ручному]]" "$a4" \
  "convert: ссылка с чужой страницы на якорь в заголовке — по тексту заголовка"
has "### Труба \\| в заголовке" "$a3" "convert: труба в самом заголовке не тронута"
has "[[#Труба в заголовке|к трубе]]" "$a3" \
  "convert: труба выкинута из фрагмента — ссылка не разваливается на алиасе"
# два якоря в одном абзаце делят его block-id: block-id у блока один
has "Двойной абзац<a name=\"дубль-два\"></a>. ^a-9f09c3b8" "$a3" \
  "convert: два якоря в абзаце дали один block-id"
has "[[#^a-9f09c3b8|раз]] и [[#^a-9f09c3b8|два]]" "$a3" \
  "convert: обе ссылки на абзац-дубль ведут в один block-id"
# якорь в ячейке: block-id там не работает, форма #id остаётся честно как есть
has "[[#в-таблице|в ячейку]]" "$a3" "convert: ссылка на якорь в ячейке осталась формой #id"
has "[[Заглушка-А-203#в-таблице|в ячейку]]" "$a4" \
  "convert: ссылка с чужой страницы на якорь в ячейке — тоже #id"
hasnt "](#" "$a3" "convert: markdown-ссылок на свой якорь не осталось"
has "На чужой якорь: потеряшка" "$a3" "convert: ссылка на несуществующий якорь стала текстом"
has "[link-miss] Заглушка-А-203.md: #нет-такого (потеряшка)" "$out" \
  "convert: якорь без цели залогирован как [link-miss]"
has "[[Заглушка-Б-204|на раздел Б]]" "$a3" \
  "convert: абсолютная ссылка с фрагментом без цели потеряла фрагмент, но не страницу"
has "[link-miss] Заглушка-А-203.md: Заглушка-Б-204#раздел-Б (на раздел Б)" "$out" \
  "convert: чужой якорь без цели тоже залогирован"
python3 -c "import json;d=json.load(open('$TMP/an/wiki/.ingest.json'));assert any(m['target']=='#нет-такого' for m in d['missing_links'])" \
  && ok || bad ".ingest.json несёт якорь без цели в missing_links"
python3 "$SK/link-check/scripts/link_check.py" "$TMP/an/wiki" --no-orphans >/dev/null 2>&1 \
  && ok || bad "link-check: [[#якорь]] на текущую страницу не считается битой ссылкой"
# детерминизм: block-id — хэш имени якоря, второй прогон обязан дать байт-в-байт
python3 "$CV" "$AN" "$TMP/an2/wiki" >/dev/null 2>&1
diff -r "$TMP/an/wiki" "$TMP/an2/wiki" >/dev/null 2>&1 \
  && ok || bad "convert: два прогона на одной выгрузке дают байт-в-байт одно и то же"

# ── convert: дата снапшота без подвала -> mtime, но громко ──────────────────
section "convert — дата снапшота и честные ошибки"
NF="$TMP/nofooter"; cp -R "$REPO/test/fixtures/edge" "$NF"
grep -v 'Document generated' "$REPO/test/fixtures/edge/index.html" > "$NF/index.html"
err="$(python3 "$CV" "$NF" "$TMP/nf/wiki" 2>&1 >/dev/null)"
has "дату снапшота не удалось разобрать" "$err" "convert: молчаливого падения на mtime нет"
python3 -c "import json;assert json.load(open('$TMP/nf/wiki/.ingest.json'))['snapshot_date_source']=='mtime'" \
  && ok || bad ".ingest.json помечает дату как взятую из mtime"
python3 "$CV" "$TMP" "$TMP/never/wiki" >/dev/null 2>&1; [ "$?" -eq 2 ] \
  && ok || bad "convert без index.html — rc=2, а не трейсбек"
err="$(python3 "$CV" "$TMP" "$TMP/never/wiki" 2>&1 >/dev/null)"
has "нет index.html" "$err" "convert объясняет, чего не хватает"
python3 "$SK/ingest-confluence/scripts/make_index.py" >/dev/null 2>&1; [ "$?" -eq 2 ] \
  && ok || bad "make_index без аргумента — rc=2"
python3 "$SK/ingest-confluence/scripts/make_index.py" "$TMP/no-such-wiki" >/dev/null 2>&1; [ "$?" -eq 2 ] \
  && ok || bad "make_index без .pagemap.json — rc=2"
python3 - "$E/wiki" <<'PY'
import json, os, sys
w = sys.argv[1]
m = json.load(open(os.path.join(w, ".space.json"), encoding="utf-8"))
m["name"] = 'Edge "Cases"'
json.dump(m, open(os.path.join(w, ".space.json"), "w", encoding="utf-8"), ensure_ascii=False)
PY
python3 "$SK/ingest-confluence/scripts/make_index.py" "$E/wiki" >/dev/null 2>&1
has 'title: "EDGE — Edge \"Cases\""' "$(head -3 "$E/wiki/Home.md")" "make_index: кавычки в title экранированы"

# ── convert: флаги прогона персистятся, ложный дифф назван ложным ───────────
section "convert — флаги прогона и ложный дифф"
FL="$TMP/flags"; mkdir -p "$FL"
python3 "$CV" "$REPO/test/fixtures/edge" "$FL/wiki" --expand-spans >/dev/null 2>&1
python3 -c "import json;d=json.load(open('$FL/wiki/.space.json'));assert d['flags']['expand_spans'] and d['hash_algo'] and d['converter_version']" \
  && ok || bad ".space.json хранит флаги прогона, версию и алгоритм хэша"
python3 -c "import json;d=json.load(open('$FL/wiki/.space.json'));assert d['snapshot_date']=='2026-07-20' and d['spaces']['EDGE']['snapshot_date']=='2026-07-20' and 'snapshot' not in d" \
  && ok || bad ".space.json: дата снапшота названа snapshot_date и вверху, и в spaces"
err="$(python3 "$CV" "$REPO/test/fixtures/edge" "$FL/wiki" 2>&1 >/dev/null)"
has "флаги отличаются от прошлого прогона, «изменено» может быть ложным" "$err" \
  "повторный прогон с другими флагами предупреждает в stderr"
ch="$(cat "$FL/wiki/"_CHANGES-*.md 2>/dev/null)"
has "флаги отличаются от прошлого прогона, «изменено» может быть ложным" "$ch" \
  "_CHANGES несёт шапку про отличающиеся флаги"
# тот же экспорт и те же флаги, но другой --base-url: футер и source: меняются,
# содержание — нет; «изменено» должно молчать
out="$(python3 "$CV" "$REPO/test/fixtures/edge" "$FL/wiki" --base-url https://conf.example.com 2>&1)"
has "no changes vs previous snapshot" "$out" "convert: --base-url не помечает страницы изменёнными"
has "source: https://conf.example.com" "$(cat "$FL/wiki/Крайние-случаи-200.md")" \
  "convert: --base-url всё же прописан в страницу"
# .space.json прошлой версии: дата лежала в верхнеуровневом `snapshot`, и
# корпус, сконвертированный до 2.3, не должен потерять её в шапке Home.md
python3 - "$FL/wiki" <<'PY'
import json, os, sys
p = os.path.join(sys.argv[1], ".space.json")
m = json.load(open(p, encoding="utf-8"))
m["snapshot"] = m.pop("snapshot_date")
m.pop("spaces", None)
json.dump(m, open(p, "w", encoding="utf-8"), ensure_ascii=False)
PY
python3 "$SK/ingest-confluence/scripts/make_index.py" "$FL/wiki" >/dev/null 2>&1
has "Снапшот Confluence: 2026-07-20" "$(cat "$FL/wiki/Home.md")" \
  "make_index читает дату из старого поля snapshot"

# ── convert: массовое удаление и чужой спейс ────────────────────────────────
section "convert — stale-removal под охраной"
ST="$TMP/stale"; mkdir -p "$ST"
python3 "$CV" "$REPO/test/fixtures/edge" "$ST/wiki" >/dev/null 2>&1
python3 "$CV" "$REPO/test/fixtures/edge-b" "$ST/wiki" >/dev/null 2>&1
[ -f "$ST/wiki/Панели-и-таблицы-201.md" ] \
  && ok || bad "второй спейс в ту же wiki не стёр страницы первого"
[ -f "$ST/wiki/Страница-второго-спейса-301.md" ] \
  && ok || bad "второй спейс сконвертирован"
PART="$TMP/partial"; cp -R "$REPO/test/fixtures/edge" "$PART"
grep -v -E '"(202|203|204|205|206)\.html"' "$REPO/test/fixtures/edge/index.html" > "$PART/index.html"
err="$(python3 "$CV" "$PART" "$ST/wiki" --space EDGE 2>&1 >/dev/null)"
has "[stale-blocked]" "$err" "частичная выгрузка не удаляет молча"
has "--allow-mass-removal" "$err" "предупреждение называет флаг-разрешение"
[ -f "$ST/wiki/Заглушка-Б-204.md" ] \
  && ok || bad "страницы частичной выгрузки остались на диске"
ch="$(cat "$ST/wiki/"_CHANGES-*.md 2>/dev/null)"
has "массовое удаление заблокировано" "$ch" "_CHANGES объясняет, что удаление заблокировано"
python3 -c "import json;d=json.load(open('$ST/wiki/.ingest.json'));assert len(d['stale_blocked'])==5 and not d['stale_removed']" \
  && ok || bad ".ingest.json перечисляет заблокированные удаления"
python3 "$CV" "$PART" "$ST/wiki" --space EDGE --allow-mass-removal >/dev/null 2>&1
[ -f "$ST/wiki/Заглушка-Б-204.md" ] \
  && bad "--allow-mass-removal обязан удалить устаревшие страницы" || ok
[ -f "$ST/wiki/Страница-второго-спейса-301.md" ] \
  && ok || bad "--allow-mass-removal не трогает чужой спейс"

# ── convert: две выгрузки в одной wiki -> Home.md по спейсам ────────────────
section "convert — Home.md группирует дерево по спейсам"
MI="$SK/ingest-confluence/scripts/make_index.py"
MS="$TMP/multispace"; mkdir -p "$MS"
python3 "$CV" "$REPO/test/fixtures/edge" "$MS/wiki" >/dev/null 2>&1
python3 "$CV" "$REPO/test/fixtures/edge-b" "$MS/wiki" >/dev/null 2>&1
python3 "$MI" "$MS/wiki" >/dev/null 2>&1
hm="$(cat "$MS/wiki/Home.md")"
has "## 🗂️ Полное дерево страниц — EDGEB" "$hm" "make_index: дерево текущего спейса названо ключом"
has "- [[Второй-спейс-300|Второй спейс]]" "$hm" "make_index: дерево текущего спейса на месте"
has "## 🗂️ Спейс EDGE — Edge Cases" "$hm" "make_index: у чужого спейса своя секция с именем"
has "снапшот Confluence: 2026-07-20" "$hm" "make_index: у чужого спейса своя дата снапшота"
has "- [[Крайние-случаи-200|Крайние случаи]]" "$hm" "make_index: дерево чужого спейса на месте"
top="$(sed -n '/Разделы верхнего уровня/,/Полное дерево страниц/p' "$MS/wiki/Home.md")"
hasnt "Крайние-случаи-200" "$top" "make_index: корень чужого спейса не стал разделом текущего"
has "Страница-второго-спейса-301" "$top" "make_index: разделы текущего спейса на месте"
python3 -c "import json;d=json.load(open('$MS/wiki/.space.json'));assert d['key']=='EDGEB' and d['spaces']['EDGE']['snapshot_date']=='2026-07-20' and d['spaces']['EDGE']['pages']==7 and d['spaces']['EDGEB']['pages']==2" \
  && ok || bad ".space.json несёт метаданные обоих спейсов"
# повторный ингест первого спейса: секция второго на месте, а «изменено»
# считается по своему спейсу — чужие страницы не выдаются за удалённые
python3 "$CV" "$REPO/test/fixtures/edge" "$MS/wiki" >/dev/null 2>&1
python3 "$MI" "$MS/wiki" >/dev/null 2>&1
hm2="$(cat "$MS/wiki/Home.md")"
has "## 🗂️ Спейс EDGEB — Second Space" "$hm2" "make_index: при повторном ингесте секция второго спейса на месте"
has "## 🗂️ Полное дерево страниц — EDGE" "$hm2" "make_index: текущим стал переингесченный спейс"
has "Снапшот Confluence: 2026-07-20" "$hm2" "make_index: шапка несёт дату текущего спейса"
ls "$MS/wiki/"_CHANGES-* >/dev/null 2>&1 \
  && bad "_CHANGES не должен появиться: ни один спейс не менялся" || ok

# ── convert: переименование -> spec/ impact ─────────────────────────────────
section "convert — переименования в «Возможно устарели в spec/»"
RN="$TMP/rename"; mkdir -p "$RN/wiki" "$RN/spec/zz" "$RN/spec/aa"
python3 "$CV" "$REPO/test/fixtures/edge" "$RN/wiki" >/dev/null 2>&1
printf -- '- [[Заглушка-А-203]] — ссылка на старое имя\n' > "$RN/spec/zz/b.md"
printf -- '- [[Заглушка-А-203|А]] — и здесь\n' > "$RN/spec/aa/c.md"
REN="$TMP/edge-ren"; cp -R "$REPO/test/fixtures/edge" "$REN"
sed 's/>Заглушка А</>Заглушка А переименованная</' "$REPO/test/fixtures/edge/index.html" > "$REN/index.html"
out="$(python3 "$CV" "$REN" "$RN/wiki" --space EDGE 2>&1)"
ch="$(cat "$RN/wiki/"_CHANGES-*.md 2>/dev/null)"
has "## Перемещено" "$ch" "_CHANGES: переименование попало в Перемещено"
has "## Возможно устарели в spec/" "$ch" "_CHANGES: секция spec-impact есть"
has "spec/aa/c.md" "$ch" "spec-impact ловит ссылку на старый basename переименованной страницы"
has "spec/zz/b.md" "$ch" "spec-impact ловит обе ссылающиеся страницы"
python3 - "$RN/wiki" <<'PY'
import glob, os, re, sys
txt = open(sorted(glob.glob(os.path.join(sys.argv[1], "_CHANGES-*.md")))[0],
           encoding="utf-8").read()
docs = re.findall(r"^- `spec/([^`]+)`", txt, re.M)
assert docs == sorted(docs), docs
PY
[ "$?" -eq 0 ] && ok || bad "«Возможно устарели в spec/» отсортированы"

# ── convert 2.5: цвет, ссылки-заглушки, data:-картинки, ручной markdown ─────
# Заглушка transform-error несёт ac:link в data-encoded-xml — раньше пропадала
# вместе со словами. Цвет едет токенами через pandoc и восстанавливается
# span'ом только там, где он не цвет темы. data: становится файлом в assets/.
section "convert — цвет, заглушки, data:, относительные ссылки"
CL="$TMP/colour"
out="$(python3 "$CV" "$REPO/test/fixtures/colour" "$CL/wiki" 2>&1)"
c="$(cat "$CL/wiki/Цвет-и-заглушки-301.md")"
has "в [[Цель-302|CBS создан клиент]] и у него есть счет." "$c" \
  "convert: заглушка отдала текст — wikilink на страницу выгрузки, текст для чужой"
has "Чужая страница (у него есть счет)" "$out" "convert: заглушка на чужую страницу залогирована [link-miss]"
hasnt "transform-error" "$c" "convert: плейсхолдер не утёк в md"
has '<span style="color:#1f845a">Источник</span>' "$c" "convert: небазовый цвет стал span с hex из var()"
has "и обычный текст." "$c" "convert: цвет темы по умолчанию не оборачивается"
has '<span style="background-color:#ffebe6">фоном</span>' "$c" "convert: rgb() фона переведён в hex"
has 'в цвете `x` остаётся' "$c" "convert: код внутри цвета не красится"
has '| amount | <span style="background-color:#ffebe6">да</span> |' "$c" "convert: подсветка ячейки стала span в GFM"
has '| Поле | Обязательно |' "$c" "convert: нейтральная подсветка gray-subtlest не оборачивается"
has "![[301_inline_" "$c" "convert: data:-картинка стала embed"
hasnt "data:image" "$c" "convert: data:-URI в md не осталось"
ls "$CL/wiki/assets/"301_inline_*.png >/dev/null 2>&1 && ok || bad "convert: data:-картинка записана в assets/"
has "[[Цель-302|подпись]] и дальше текст" "$c" "convert: ручной [подпись](ссылка) склеен в одну ссылку"
has '[[Цель-302|обычная]] <span style="color:#1f845a">[[Цель-302|зелёная]]</span>' "$c" \
  "convert: ссылка с частично цветной подписью поделена на ссылки по цвету"
has '<span style="color:#c9372c">[[Цель-302|красная]]</span>' "$c" "convert: целиком цветная ссылка обёрнута целиком"
has "Вложение вне выгрузки: f.pdf." "$c" "convert: относительная ссылка вне выгрузки без --base-url стала текстом"
has "f.pdf?version=1 (f.pdf)" "$out" "convert: она же залогирована [link-miss]"
python3 -c "import json;d=json.load(open('$CL/wiki/.ingest.json'));assert 'colour_lost' in d and d['converter_changed'] is False" \
  && ok || bad ".ingest.json несёт colour_lost и converter_changed"
CB="$TMP/colour-base"
python3 "$CV" "$REPO/test/fixtures/colour" "$CB/wiki" --base-url https://conf.example.com >/dev/null 2>&1
has "[f.pdf](https://conf.example.com/download/attachments/1/f.pdf?version=1)" \
  "$(cat "$CB/wiki/Цвет-и-заглушки-301.md")" "convert: с --base-url относительная ссылка стала абсолютной"
python3 - "$CB/wiki/.space.json" <<'PY'
import json, sys
p = sys.argv[1]; d = json.load(open(p, encoding="utf-8")); d["converter_version"] = "2.4"
json.dump(d, open(p, "w", encoding="utf-8"), ensure_ascii=False)
PY
err="$(python3 "$CV" "$REPO/test/fixtures/colour" "$CB/wiki" --base-url https://conf.example.com 2>&1 >/dev/null)"
has "версия конвертера сменилась (2.4 → 2.5)" "$err" "convert: смена версии конвертера предупреждается в stderr"
python3 -c "import json;d=json.load(open('$CB/wiki/.ingest.json'));assert d['converter_changed'] is True" \
  && ok || bad ".ingest.json: converter_changed = true после смены версии"

else
section "convert — ПРОПУЩЕНО (нет pandoc/lxml)"
fi
