# Самотесты loft — 80-install. Подключается из test/run.sh; переменные REPO/SK/HK/TMP
# и функции ok/bad/has/hasnt/section приходят оттуда.

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

# ── переустановка не уносит в бэкап настройку Claude Code ──────────────────
mkdir -p "$I1/.claude/commands" "$I1/.claude/rules" "$I1/.claude/output-styles"
echo '{"permissions":{"allow":["Bash(ls:*)"]}}' > "$I1/.claude/settings.local.json"
echo "команда" > "$I1/.claude/commands/my-cmd.md"
echo "правило" > "$I1/.claude/rules/my-rule.md"
echo "стиль"   > "$I1/.claude/output-styles/my-style.md"
out="$(bash "$REPO/install.sh" "$I1" 2>&1)"
has "перенесена пользовательская настройка" "$out" "инсталлер называет перенесённое"
[ -f "$I1/.claude/settings.local.json" ] && ok || bad "settings.local.json (разрешения) пережил переустановку"
[ -f "$I1/.claude/commands/my-cmd.md" ] && [ -f "$I1/.claude/rules/my-rule.md" ] \
  && ok || bad "commands/ и rules/ пережили переустановку"
[ -f "$I1/.claude/output-styles/my-style.md" ] && [ -f "$I1/.claude/output-styles/analyst.md" ] \
  && ok || bad "свой output-style уцелел рядом с ядровым"

# ── раскладка корпуса заведена целиком ─────────────────────────────────────
[ -f "$I1/inbox/done/.gitkeep" ] && ok || bad "inbox/done создан"
[ -f "$I1/spec/_reference/.gitkeep" ] && [ -f "$I1/spec/_reviews/.gitkeep" ] \
  && ok || bad "spec/_reference и spec/_reviews созданы"

# ── .gitignore без завершающего перевода строки не склеивается ─────────────
I5="$TMP/i5"; mkdir -p "$I5"; printf 'node_modules' > "$I5/.gitignore"
bash "$REPO/install.sh" "$I5" >/dev/null 2>&1
grep -qxF 'node_modules' "$I5/.gitignore" && grep -qxF '.secrets.env' "$I5/.gitignore" \
  && ok || bad "последний паттерн .gitignore не склеился с .secrets.env"

# ── два запуска в одну секунду: бэкапы рядом, а не вложенно ────────────────
FB="$TMP/fakebin"; mkdir -p "$FB"
printf '#!/bin/sh\necho 20260101000000\n' > "$FB/date"; chmod +x "$FB/date"
I6="$TMP/i6"; mkdir -p "$I6/.claude"; echo "прежнее" > "$I6/.claude/marker"
PATH="$FB:$PATH" bash "$REPO/install.sh" "$I6" >/dev/null 2>&1
PATH="$FB:$PATH" bash "$REPO/install.sh" "$I6" >/dev/null 2>&1
cnt="$(ls -d "$I6"/.claude.bak.* 2>/dev/null | wc -l | tr -d ' ')"
[ "$cnt" = "2" ] && ok || bad "два бэкапа рядом (найдено: $cnt)"
[ ! -e "$I6/.claude.bak.20260101000000/.claude.bak.20260101000000" ] \
  && ok || bad "бэкап не вложился в бэкап"

# ── .mcp.json: в бэкап уезжает только специосовский ────────────────────────
I7="$TMP/i7"; mkdir -p "$I7"
printf '%s\n' '{"mcpServers":{"serena":{"command":"uvx","args":["--from","git+https://github.com/oraios/serena","serena-mcp-server"],"env":{"NOTE":"мигрировано со specos"}}}}' > "$I7/.mcp.json"
out="$(bash "$REPO/install.sh" "$I7" 2>&1)"
has ".mcp.json оставлен как есть" "$out" "чужой .mcp.json со словом specos не трогаем"
[ -f "$I7/.mcp.json" ] && ok || bad "чужой .mcp.json остался на месте"
printf '%s\n' '{"mcpServers":{"specos-memory":{"command":"node","args":["/opt/specos/mcp/memory.js"]}}}' > "$I7/.mcp.json"
out="$(bash "$REPO/install.sh" "$I7" 2>&1)"
[ ! -f "$I7/.mcp.json" ] && ok || bad "specos'овский .mcp.json уехал в бэкап"
printf '%s' 'не json вовсе' > "$I7/.mcp.json"
out="$(bash "$REPO/install.sh" "$I7" 2>&1)"
has "не разобрался" "$out" "битый .mcp.json — предупреждение, не бэкап"
[ -f "$I7/.mcp.json" ] && ok || bad "битый .mcp.json остался на месте"

# ── провал самопроверки откатывает установку (python3 сломан через PATH) ───
I8="$TMP/i8"; mkdir -p "$I8/.claude"; echo "прежнее ядро" > "$I8/.claude/marker"
PB="$TMP/pybad"; mkdir -p "$PB"; printf '#!/bin/sh\nexit 1\n' > "$PB/python3"; chmod +x "$PB/python3"
out="$(PATH="$PB:$PATH" bash "$REPO/install.sh" "$I8" 2>&1)" && rc=0 || rc=$?
[ "$rc" != "0" ] && ok || bad "провал самопроверки — ненулевой код возврата"
has "САМОПРОВЕРКА ПРОВАЛЕНА" "$out" "самопроверка поймала битую установку"
has "прежний .claude вернулся на место" "$out" "инсталлер сказал про откат"
[ -f "$I8/.claude/marker" ] && ok || bad "прежний .claude вернулся из бэкапа"
ls -d "$I8"/.claude.bak.* >/dev/null 2>&1 && bad "бэкап не остался мусором" || ok

# ── build-archive: герметичная сборка и обезличенный tar ───────────────────
# Кейс запускает настоящую сборку в копии репозитория. Релизный гейт в копии
# подменён стабом: гонять весь набор второй раз — это те же кейсы повторно.
# Что гейт реально зовётся и умеет отменить сборку, проверяет провальный стаб.
if [ "${LOFT_BUILD_GATE:-0}" = "1" ]; then
  section "build-archive — пропущен (вложенный прогон из самой сборки)"
else
  section "build-archive — сборка дистрибутива"
  B="$TMP/ba"; mkdir -p "$B/xdg/loft"
  for e in VERSION install.sh build-archive.sh README.md README.ru.md LICENSE \
           NOTICE CHANGELOG.md bundle docs test; do
    cp -R "$REPO/$e" "$B/$e"
  done
  GATE="$B/test/run.sh"

  # Гейт провален — упаковки не происходит, и сборка показывает, чем именно.
  printf '#!/usr/bin/env bash\necho "FAIL: стаб"\nprintf "\\nитого: 0 ok, 1 fail\\n"\nexit 1\n' > "$GATE"
  out="$(XDG_CACHE_HOME="$B/xdg" bash "$B/build-archive.sh" 2>&1)" && rc=0 || rc=$?
  [ "$rc" != "0" ] && ok || bad "проваленный гейт отменяет сборку"
  has "ПРОВАЛЕН" "$out" "сборка сказала, что самотесты провалены"
  has "FAIL: стаб" "$out" "сборка показала провалившую строку набора"
  [ ! -d "$B/dist" ] && ok || bad "при проваленном гейте ничего не упаковано"

  printf '#!/usr/bin/env bash\nprintf "\\nитого: 0 ok, 0 fail\\n"\nexit 0\n' > "$GATE"
  # «На GitHub уже есть релиз новее» — сборка не должна об это спотыкаться.
  printf '%s\n%s\n' "$(date +%s)" "9.9.9" > "$B/xdg/loft/latest-bogdanov-igor-loft"
  out="$(XDG_CACHE_HOME="$B/xdg" bash "$B/build-archive.sh" 2>&1)" && rc=0 || rc=$?
  [ "$rc" = "0" ] && ok \
    || bad "сборка проходит при «новом релизе» в кэше: $(printf '%s' "$out" | tail -3 | tr '\n' ' ')"
  BVER="$(tr -d '[:space:]' < "$REPO/VERSION")"
  [ -f "$B/dist/loft_$BVER.tgz" ] && ok || bad "архив собран"
  lst="$(TZ=UTC tar -tvf "$B/dist/loft_$BVER.tgz" 2>/dev/null)"
  hasnt "$(id -un)" "$lst" "в заголовках tar нет имени сборщика"
  has "loft/install.sh" "$lst" "архив несёт инсталлер"
  # Владелец и время в заголовках прибиты гвоздями — 0/0 и 2020-01-01 UTC.
  # Печатают их реализации по-разному: GNU tar «0/0» и ISO-дату, bsdtar «0 0»
  # и «Jan  1  2020», — поэтому проверка признаёт обе записи.
  case "$lst" in *" 0/0 "*|*" 0 0 "*) ok ;; *) bad "владелец в заголовках обезличен в 0/0" ;; esac
  case "$lst" in *"2020-01-01 00:00"*|*"Jan  1  2020"*) ok ;;
                 *) bad "время файлов зафиксировано на 2020-01-01 UTC" ;; esac
  # sha256 рядом с архивом — расписка получателю: пересборка того же тега
  # обязана дать тот же архив, иначе сверять нечего.
  sha="$(cut -d' ' -f1 < "$B/dist/loft_$BVER.tgz.sha256")"
  XDG_CACHE_HOME="$B/xdg" bash "$B/build-archive.sh" >/dev/null 2>&1
  [ "$sha" = "$(cut -d' ' -f1 < "$B/dist/loft_$BVER.tgz.sha256")" ] \
    && ok || bad "пересборка даёт тот же sha256"

  # ── та же сборка под GNU tar: байты не зависят от реализации tar ──────────
  # Упаковывает python3, системный tar остаётся только у получателя — значит
  # сборка под GNU tar обязана дать те же байты, что под bsdtar. Заодно самотест
  # внутри сборки распаковывает и ставит архив тем tar, что первым в PATH.
  GNUBIN="$(brew --prefix gnu-tar 2>/dev/null)/libexec/gnubin"
  if [ -x "$GNUBIN/tar" ]; then
    section "build-archive — под GNU tar"
    rm -rf "$B/dist"
    out="$(PATH="$GNUBIN:$PATH" XDG_CACHE_HOME="$B/xdg" bash "$B/build-archive.sh" 2>&1)" \
      && rc=0 || rc=$?
    [ "$rc" = "0" ] && ok \
      || bad "сборка и её самотест под GNU tar: $(printf '%s' "$out" | tail -3 | tr '\n' ' ')"
    [ -f "$B/dist/loft_$BVER.tgz" ] && ok || bad "GNU tar: архив собран"
    [ "$sha" = "$(cut -d' ' -f1 < "$B/dist/loft_$BVER.tgz.sha256")" ] \
      && ok || bad "GNU tar: тот же sha256, что под bsdtar"
    glst="$(PATH="$GNUBIN:$PATH" TZ=UTC tar -tvf "$B/dist/loft_$BVER.tgz" 2>/dev/null)"
    has " 0/0 " "$glst" "GNU tar: владелец обезличен в 0/0"
    tar -tf "$B/dist/loft_$BVER.tgz" >/dev/null 2>&1 && ok \
      || bad "GNU tar: собранный архив читается штатным tar получателя"
  else
    section "build-archive — под GNU tar ПРОПУЩЕНО (нет gnu-tar/gnubin)"
  fi
fi

# ── install: сид профиля документации ────────────────────────────────────────
section "install — сид spec/_STRUCTURE.md"
I3="$TMP/i3"; mkdir -p "$I3"
bash "$REPO/install.sh" "$I3" >/dev/null 2>&1
[ -f "$I3/spec/_STRUCTURE.md" ] && ok || bad "свежая установка сеет spec/_STRUCTURE.md"
has "## Голос" "$(cat "$I3/spec/_STRUCTURE.md")" "в сиде есть секция «Голос»"
echo "# мой профиль" > "$I3/spec/_STRUCTURE.md"
bash "$REPO/install.sh" "$I3" >/dev/null 2>&1
[ "$(cat "$I3/spec/_STRUCTURE.md")" = "# мой профиль" ] && ok || bad "переустановка не перезаписывает профиль"
