# Самотесты loft — 20-tablemd. Подключается из test/run.sh; переменные REPO/SK/HK/TMP
# и функции ok/bad/has/hasnt/section приходят оттуда.

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

# ── tablemd: готовый markdown в ячейке (md_cells) ───────────────────────────
# Ячейка старой wiki уже несёт markdown ([[ссылку]], **болд**, `код`):
# экранирование превращало его в мусор. Режим включается только вызовом
# fix_tables (md_cells=True) — вывод convert.py не меняется.
section "tablemd — markdown в ячейке"
out="$(python3 - "$SK/ingest-confluence/scripts" <<'EOF'
import sys; sys.path.insert(0, sys.argv[1])
from lxml import html as H
import tablemd
src = ('<table><tr><th>Что</th><th>Где</th></tr>'
       '<tr><td>[[СИ-1|Регистрация]], **важно**, `a|b`</td>'
       '<td>обычный текст_с_ [скобками]</td></tr></table>')
print("MD")
print(tablemd.table_to_gfm(H.fragment_fromstring(src), md_cells=True))
print("PLAIN")
print(tablemd.table_to_gfm(H.fragment_fromstring(src)))
EOF
)"
md="${out#*MD}"; md="${md%%PLAIN*}"; plain="${out##*PLAIN}"
has '[[СИ-1\|Регистрация]]' "$md" "md_cells: wikilink не экранирован, пайп внутри — экранирован"
has '**важно**' "$md" "md_cells: болд не экранирован"
has '`a\|b`' "$md" "md_cells: инлайн-код цел, пайп экранирован"
has '\[скобками\]' "$md" "md_cells: соседняя ячейка без markdown экранируется как раньше"
has '\[\[СИ-1\|Регистрация\]\]' "$plain" "по умолчанию (convert.py) экранирование прежнее"
has '\*\*важно\*\*' "$plain" "по умолчанию болд экранируется"

# ── tablemd: цвет ячейки и цветной span (convert.py 2.5) ────────────────────
section "tablemd — цвет ячейки и span"
out="$(python3 - "$SK/ingest-confluence/scripts" <<'EOF'
import sys; sys.path.insert(0, sys.argv[1])
from lxml import html as H
import tablemd
t = H.fragment_fromstring('<table><tr><th>А</th><th>Б</th></tr>'
    '<tr><td style="background-color:#ffebe6">да</td>'
    '<td><span style="color:#1f845a">x</span> и <span style="color: red; font-weight:bold">y</span></td></tr>'
    '<tr><td style="background-color:#ffebe6">  </td><td>z</td></tr></table>')
print(tablemd.table_to_gfm(t))
print("CANON:%r|%r" % (tablemd.canon_style("color:#1f845a;background-color:#ffebe6"), tablemd.canon_style("color: red")))
EOF
)"
has '| <span style="background-color:#ffebe6">да</span> |' "$out" "подсветка ячейки стала span вокруг содержимого"
has '<span style="color:#1f845a">x</span> и y' "$out" "канонический span цел, чужой стиль прозрачен"
has '|  | z |' "$out" "пустая подсвеченная ячейка не получает пустой span"
has "CANON:'color:#1f845a;background-color:#ffebe6'|''" "$out" "canon_style принимает только форму конвертера"
