# Самотесты loft — 70-deliver-pdf. Подключается из test/run.sh; переменные REPO/SK/HK/TMP
# и функции ok/bad/has/hasnt/section приходят оттуда.

EP="$SK/deliver-pdf/scripts/export_pdf.py"
P="$TMP/pdf"; mkdir -p "$P/spec/qr" "$P/wiki" "$P/assets" "$P/pack"
echo "# Цель" > "$P/wiki/Цель-1.md"
printf 'PNG-заглушка' > "$P/assets/схема.png"
printf -- '---\ntitle: "Тест"\nstatus: review\n---\n\n# Тест\n\nСм. [[Цель-1|конвенцию]] и `код`.\n\n![[схема.png]]\n' > "$P/spec/док.md"
# вложенный: паспорт с CRLF и одинарными кавычками, embed ищется от корня проекта
printf -- '---\r\ntitle: '"'"'Вложенный ТЗ'"'"'\r\n---\r\nEmbed: ![[схема.png]] и [[Цель-1]]\r\n' > "$P/spec/qr/вложенный.md"
printf -- '---\ntitle: Битый\n---\nСсылка [[нет-такой]].\n' > "$P/spec/битый.md"

# ── deliver-pdf: аргументы и каталог вывода ─────────────────────────────────
section "deliver-pdf — аргументы"
out="$(python3 "$EP" "$P/spec/док.md" --engine мусор 2>&1)"; rc=$?
[ "$rc" -eq 2 ] && ok || bad "--engine мусор: rc=2 (got $rc)"
has "допустимы" "$out" "--engine мусор: перечислены допустимые движки"
out="$(python3 "$EP" "$P/spec/док.md" -o "$P/spec/док.md/x.pdf" 2>&1)"; rc=$?
[ "$rc" -eq 2 ] && ok || bad "-o в невозможный каталог: rc=2 (got $rc)"
has "не удалось создать каталог" "$out" "-o в невозможный каталог: честное сообщение"
out="$(python3 "$EP" "$P/spec/док.md" "$P/spec/qr/вложенный.md" 2>&1)"; rc=$?
[ "$rc" -eq 2 ] && ok || bad "два документа без --bundle: rc=2 (got $rc)"

# ── deliver-pdf: markdown-пакет (pandoc не нужен) ───────────────────────────
section "deliver-pdf — --md и --bundle"
out="$(python3 "$EP" --md "$P/pack/один.md" "$P/spec/док.md" 2>&1)"; rc=$?
[ "$rc" -eq 0 ] && ok || bad "--md: rc=0 (got $rc): $out"
m="$(cat "$P/pack/один.md" 2>/dev/null)"
has "# Тест" "$m" "--md: заголовок документа на месте"
hasnt "status: review" "$m" "--md: паспорт-frontmatter снят"
has "конвенцию" "$m" "--md: wikilink разрешился в текст"
hasnt "[[" "$m" "--md: сырых wikilinks не осталось"
has "![схема.png](../assets/схема.png)" "$m" "--md: embed стал относительным путём"
out="$(python3 "$EP" --md "$P/pack/вложенный.md" "$P/spec/qr/вложенный.md" 2>&1)"
has "# Вложенный ТЗ" "$(cat "$P/pack/вложенный.md" 2>/dev/null)" \
  "--md: title из CRLF-паспорта в одинарных кавычках"
out="$(python3 "$EP" --bundle "$P/pack/пакет.md" "$P/spec/док.md" "$P/spec/qr/вложенный.md" 2>&1)"; rc=$?
[ "$rc" -eq 0 ] && ok || bad "--bundle: rc=0 (got $rc): $out"
b="$(cat "$P/pack/пакет.md" 2>/dev/null)"
has "# Тест" "$b" "--bundle: первый документ под своим H1"
has "# Вложенный ТЗ" "$b" "--bundle: второй документ под своим H1"
[ "$(grep -c '^# ' "$P/pack/пакет.md" 2>/dev/null)" -eq 2 ] && ok || bad "--bundle: ровно два H1"
has "(../assets/схема.png)" "$b" "--bundle: embed вложенного документа найден от корня"

# ── deliver-pdf: неразрешённые ссылки ───────────────────────────────────────
section "deliver-pdf — битые ссылки"
out="$(python3 "$EP" --md "$P/pack/битый.md" "$P/spec/битый.md" 2>&1)"; rc=$?
has "не разрешено: 1" "$out" "битый wikilink попал в предупреждение"
has "нет-такой" "$out" "предупреждение называет цель"
[ "$rc" -eq 0 ] && ok || bad "битая ссылка без --strict: rc=0 (got $rc)"
rm -f "$P/pack/строгий.md"
out="$(python3 "$EP" --md "$P/pack/строгий.md" "$P/spec/битый.md" --strict 2>&1)"; rc=$?
[ "$rc" -eq 1 ] && ok || bad "--strict при битой ссылке: rc=1 (got $rc)"
[ ! -f "$P/pack/строгий.md" ] && ok || bad "--strict: выход не записан"

# ── deliver-pdf: PDF и honest-fallback ──────────────────────────────────────
if command -v pandoc >/dev/null 2>&1; then
section "deliver-pdf — экспортёр"
printf 'СТАРЫЙ-PDF' > "$P/spec/док.pdf"
out="$(python3 "$EP" "$P/spec/док.md" 2>&1)"; rc=$?
case "$rc" in
  0) ok
     if grep -q "СТАРЫЙ-PDF" "$P/spec/док.pdf" 2>/dev/null; then
       bad "сдан старый PDF: файл не перезаписан"
     else
       [ -s "$P/spec/док.pdf" ] && ok || bad "PDF пуст"
     fi ;;
  3) ok
     [ -s "$P/spec/док.html" ] && ok || bad "fallback-HTML не оставлен" ;;
  *) bad "export_pdf упал (rc=$rc): $out"; bad "результат не проверен" ;;
esac

out="$(python3 "$EP" "$P/spec/док.md" -o "$P/нет-каталога/док.pdf" --engine html 2>&1)"; rc=$?
[ "$rc" -eq 0 ] && ok || bad "--engine html: rc=0 (got $rc): $out"
[ -s "$P/нет-каталога/док.html" ] && ok || bad "-o в несуществующий каталог: каталог создан, файл записан"
h="$(cat "$P/нет-каталога/док.html" 2>/dev/null)"
has "конвенцию" "$h" "html: wikilink разрешился в текст"
hasnt "[[" "$h" "html: сырых wikilinks не осталось"
hasnt "status: review" "$h" "html: паспорт-frontmatter снят"
has "data:image" "$h" "html: embed вшит в файл"
hasnt 'class="title"' "$h" "html: свой H1 документа не продублирован title-блоком"

python3 "$EP" "$P/spec/qr/вложенный.md" -o "$P/pack/вложенный.pdf" --engine html >/dev/null 2>&1
v="$(cat "$P/pack/вложенный.html" 2>/dev/null)"
has "data:image" "$v" "вложенный spec/qr/: embed найден от корня проекта"
has 'class="title"' "$v" "без своего H1 заголовок берётся из паспорта"

# движок вернул 0 и ничего не записал — сдавать старый PDF нельзя
printf '#!/bin/sh\nexit 0\n' > "$P/stub-chrome"; chmod +x "$P/stub-chrome"
printf 'СТАРЫЙ-PDF' > "$P/spec/док.pdf"
out="$(LOFT_CHROME="$P/stub-chrome" python3 "$EP" "$P/spec/док.md" --engine chrome 2>&1)"; rc=$?
[ "$rc" -eq 2 ] && ok || bad "молчащий движок: rc=2 (got $rc): $out"
has "не собран" "$out" "молчащий движок: сдача названа несобранной"
has "не записан" "$out" "молчащий движок: сказано, что файл не появился"
grep -q "СТАРЫЙ-PDF" "$P/spec/док.pdf" 2>/dev/null && ok || bad "старый PDF затёрт при провале движка"
has "устарел" "$out" "про старый PDF сказано, что он устарел"

# ── deliver-pdf: движок не отвечает — попытку обрывает таймаут ──────────────
# LOFT_ENGINE_TIMEOUT — тест-ручка: боевые 180 с в наборе не высидеть.
section "deliver-pdf — таймаут движка"
printf '#!/bin/sh\nsleep 5\n' > "$P/stub-slow"; chmod +x "$P/stub-slow"
t0="$(date +%s)"
out="$(LOFT_CHROME="$P/stub-slow" LOFT_ENGINE_TIMEOUT=1 \
       python3 "$EP" "$P/spec/док.md" -o "$P/медленный.pdf" --engine chrome 2>&1)"; rc=$?
t1="$(date +%s)"
[ "$rc" -eq 2 ] && ok || bad "зависший движок: rc=2 (got $rc): $out"
[ "$((t1 - t0))" -lt 4 ] && ok || bad "зависший движок оборван по таймауту (ждали $((t1 - t0)) с)"
has "не ответил за 1 с" "$out" "таймаут назван в отчёте"
has "не собран" "$out" "после таймаута сдача названа несобранной"
[ -s "$P/медленный.html" ] && ok || bad "после таймаута оставлен HTML для печати из браузера"

# ── deliver-pdf: typst — первый движок цепочки ─────────────────────────────
if command -v typst >/dev/null 2>&1; then
section "deliver-pdf — typst"
# typst разбирает картинку по-настоящему, в отличие от HTML-движков: строке
# вместо PNG он не верит, поэтому у секции своя настоящая картинка.
python3 - "$P/assets/точка.png" <<'PNG'
import base64, sys
open(sys.argv[1], "wb").write(base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"
    "AAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="))
PNG
printf -- '---\ntitle: "Паспортный титул"\n---\n\n# Свой заголовок\n\nСм. [[Цель-1|конвенцию]].\n\n| Колонка А | Колонка Б |\n|---|---|\n| значение | ещё значение |\n\n![[точка.png]]\n' > "$P/spec/типст.md"
out="$(python3 "$EP" "$P/spec/типст.md" -o "$P/типст.pdf" --engine typst 2>&1)"; rc=$?
[ "$rc" -eq 0 ] && ok || bad "--engine typst: rc=0 (got $rc): $out"
has "(typst)" "$out" "--engine typst: отчитался typst"
[ -s "$P/типст.pdf" ] && ok || bad "--engine typst: PDF непустой"
head -c 4 "$P/типст.pdf" | grep -q '%PDF' && ok || bad "--engine typst: на выходе PDF, а не что-то ещё"
out="$(python3 "$EP" "$P/spec/типст.md" -o "$P/типст-auto.pdf" --engine auto 2>&1)"; rc=$?
[ "$rc" -eq 0 ] && ok || bad "--engine auto с typst: rc=0 (got $rc): $out"
has "(typst)" "$out" "--engine auto: typst первый в цепочке"
if command -v pdftotext >/dev/null 2>&1; then
  t="$(pdftotext "$P/типст.pdf" - 2>/dev/null)"
  has "Свой заголовок" "$t" "typst: кириллический заголовок в текстовом слое"
  has "конвенцию" "$t" "typst: wikilink разрешился в текст"
  has "Колонка А" "$t" "typst: таблица на месте"
  has "ещё значение" "$t" "typst: ячейки таблицы на месте"
  hasnt "Паспортный титул" "$t" "typst: свой H1 не продублирован титулом из паспорта"
  [ "$(printf '%s\n' "$t" | grep -c 'Свой заголовок')" -eq 1 ] && ok || bad "typst: заголовок двоится"
  has "Свой заголовок" "$(pdftotext "$P/типст-auto.pdf" - 2>/dev/null)" \
    "typst через auto: текст на месте"
else
  [ "$(wc -c < "$P/типст.pdf" | tr -d ' ')" -gt 2000 ] && ok \
    || bad "typst: PDF подозрительно мал (текстовый слой не проверить — нет pdftotext)"
fi
# без своего H1 титул печатается из паспорта
printf -- '---\ntitle: "Титул из паспорта"\n---\nТело без своего H1.\n' > "$P/spec/типст-титул.md"
out="$(python3 "$EP" "$P/spec/типст-титул.md" -o "$P/типст-титул.pdf" --engine typst 2>&1)"; rc=$?
[ "$rc" -eq 0 ] && ok || bad "typst без своего H1: rc=0 (got $rc): $out"
if command -v pdftotext >/dev/null 2>&1; then
  has "Титул из паспорта" "$(pdftotext "$P/типст-титул.pdf" - 2>/dev/null)" \
    "typst: без своего H1 заголовок берётся из паспорта"
fi

# упавший typst: старый PDF остаётся, и об этом сказано — как у прочих движков
printf 'не картинка' > "$P/assets/битая.png"
printf -- '---\ntitle: Битая\n---\n\n# Битая\n\n![[битая.png]]\n' > "$P/spec/типст-битый.md"
printf 'СТАРЫЙ-PDF' > "$P/типст-старый.pdf"
out="$(python3 "$EP" "$P/spec/типст-битый.md" -o "$P/типст-старый.pdf" --engine typst 2>&1)"; rc=$?
[ "$rc" -eq 2 ] && ok || bad "провал typst: rc=2 (got $rc): $out"
has "typst" "$out" "провал typst назван по имени движка"
grep -q "СТАРЫЙ-PDF" "$P/типст-старый.pdf" 2>/dev/null && ok || bad "старый PDF затёрт при провале typst"
has "устарел" "$out" "про старый PDF после провала typst сказано, что он устарел"
[ -s "$P/типст-старый.html" ] && ok || bad "после провала typst оставлен HTML для печати из браузера"

# В системе только typst, и он упал: отчёт обязан назвать его, а не объявить,
# что PDF-движка нет, и посоветовать поставить typst — он уже стоит.
ONLY="$P/only"; mkdir -p "$ONLY"
ln -sf "$(command -v pandoc)" "$ONLY/pandoc"; ln -sf "$(command -v typst)" "$ONLY/typst"
out="$(PATH="$ONLY" LOFT_CHROME="$P/нет-такого-хрома" \
       "$(command -v python3)" "$EP" "$P/spec/типст-битый.md" \
       -o "$P/только-typst.pdf" --engine auto 2>&1)"; rc=$?
[ "$rc" -eq 2 ] && ok || bad "auto: упавший typst — провал сборки, rc=2 (got $rc): $out"
has "typst" "$out" "auto: отчёт называет упавший typst"
hasnt "PDF-движка нет" "$out" "auto: упавший движок не выдан за отсутствие движков"
else
section "deliver-pdf — typst ПРОПУЩЕНО (нет typst)"
fi
else
section "deliver-pdf — экспортёр ПРОПУЩЕН (нет pandoc)"
fi
