#!/usr/bin/env bash
# Сборка дистрибутива: dist/loft_<version>.tgz + .sha256 рядом.
# Архив распаковывается в одну папку loft/; в проекте:
#   tar -xzf loft_<version>.tgz && bash loft/install.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd -P)"
VER="$(tr -d '[:space:]' < "$ROOT/VERSION")"
OUT="$ROOT/dist"
STAGE="$(mktemp -d)"
CACHE="$(mktemp -d)"
trap 'rm -rf "$STAGE" "$CACHE"' EXIT

# Сборка герметична: ни один её шаг не пишет в настоящий ~/.cache и не ходит в
# сеть. Кэш update-check — во временный каталог, посеянный заведомо старой
# версией; сам хук выключён везде, кроме одной проверки ниже, которая его
# включает явно. Без этого сборка падала, когда на GitHub появлялся релиз
# новее собираемого.
export XDG_CACHE_HOME="$CACHE"
export LOFT_NO_UPDATE_CHECK=1
mkdir -p "$CACHE/loft"
printf '%s\n%s\n' "$(date +%s)" "0.0.1" > "$CACHE/loft/latest-bogdanov-igor-loft"

# Релизный гейт: самотесты ядра до любой упаковки. LOFT_BUILD_GATE говорит
# кейсу самой сборки не запускать её рекурсивно — остальные кейсы идут все.
if ! gate="$(LOFT_BUILD_GATE=1 bash "$ROOT/test/run.sh" 2>&1)"; then
  echo "loft: test/run.sh ПРОВАЛЕН — сборка отменена" >&2
  printf '%s\n' "$gate" | grep -E 'FAIL:|^итого:' >&2
  exit 1
fi

mkdir -p "$STAGE/loft" "$OUT"
# Доки и лицензия едут внутри архива: получатель tgz получает полный
# мануал на двух языках оффлайн, не заходя в репо.
cp "$ROOT/README.md" "$ROOT/README.ru.md" "$ROOT/LICENSE" "$ROOT/NOTICE" \
   "$ROOT/CHANGELOG.md" "$ROOT/VERSION" "$ROOT/install.sh" "$STAGE/loft/"
cp -R "$ROOT/bundle" "$STAGE/loft/bundle"
cp -R "$ROOT/docs" "$STAGE/loft/docs"
find "$STAGE" -name '.DS_Store' -delete
chmod +x "$STAGE/loft/install.sh"
find "$STAGE/loft/bundle" -name '*.sh' -exec chmod +x {} +

TGZ="$OUT/loft_${VER}.tgz"
# Упаковывает python3 (stdlib tarfile+gzip), а не системный tar. Ветвление на
# bsdtar/GNU tar давало разные байты на одном и том же дереве — реализации
# по-разному набивают восьмеричные поля заголовка, — и sha256 был воспроизводим
# только в пределах одной ОС. Здесь фиксировано всё, что зависело от машины и
# сборщика: формат ustar, порядок записей по байтам пути, uid/gid 0 и пустые
# имена владельцев (иначе в заголовок едет имя пользователя сборщика), права
# 0755 каталогам и исполняемым и 0644 остальным, время 2020-01-01 UTC вместо
# момента cp, gzip без имени и времени файла в потоке и с фиксированным
# уровнем. Распаковывается обычным tar -xzf любой реализации.
python3 - "$STAGE" "$TGZ" <<'PY'
import gzip, os, sys, tarfile

stage, out = sys.argv[1], sys.argv[2]
MTIME = 1577836800  # 2020-01-01 00:00:00 UTC

paths = []
for base, _dirs, files in os.walk(os.path.join(stage, "loft")):
    rel = os.path.relpath(base, stage)
    paths.append(rel)
    paths.extend(os.path.join(rel, f) for f in files)
paths.sort(key=lambda p: p.encode())

with open(out, "wb") as raw, \
     gzip.GzipFile(filename="", mode="wb", compresslevel=9, mtime=0, fileobj=raw) as gz, \
     tarfile.open(fileobj=gz, mode="w", format=tarfile.USTAR_FORMAT) as tar:
    for rel in paths:
        full = os.path.join(stage, rel)
        st = os.stat(full)
        isdir = os.path.isdir(full)
        ti = tarfile.TarInfo(rel)
        ti.type = tarfile.DIRTYPE if isdir else tarfile.REGTYPE
        ti.mode = 0o755 if isdir or st.st_mode & 0o100 else 0o644
        ti.size = 0 if isdir else st.st_size
        ti.mtime = MTIME
        ti.uid = ti.gid = 0
        ti.uname = ti.gname = ""
        if isdir:
            tar.addfile(ti)
        else:
            with open(full, "rb") as f:
                tar.addfile(ti, f)
PY
( cd "$OUT" && shasum -a 256 "loft_${VER}.tgz" > "loft_${VER}.tgz.sha256" )

# Самотест: распаковать во временный каталог и реально установить.
T="$(mktemp -d)"
( cd "$T" && tar -xzf "$TGZ" && bash loft/install.sh >/dev/null )
fail() { echo "loft: самотест архива ПРОВАЛЕН — $1 (площадка сохранена: $T)" >&2; exit 1; }
[ -f "$T/.claude/CLAUDE.md" ]                        || fail "нет контракта"
[ -f "$T/BACKLOG.md" ] && [ -f "$T/QUESTIONS.md" ]   || fail "сиды не посеяны"
[ -f "$T/memory/MEMORY.md" ]                         || fail "нет индекса памяти"
[ -d "$T/spec" ] && [ -d "$T/inbox" ]                || fail "нет каталогов корпуса"
[ -x "$T/.claude/hooks/leak-guard.sh" ] && [ -x "$T/.claude/hooks/update-check.sh" ] \
                                                     || fail "хуки не исполняемые"
[ -x "$T/.claude/skills/migrate-specos/sweep.sh" ]   || fail "sweep не исполняемый"
[ "$(cat "$T/.claude/VERSION")" = "$VER" ]           || fail "версия не проштампована"
[ "$(ls "$T/.claude/skills" | wc -l | tr -d ' ')" -ge 15 ] || fail "скиллов меньше 15"
out="$(cd "$T" && CLAUDE_PROJECT_DIR="$T" LOFT_NO_UPDATE_CHECK=0 \
       bash .claude/hooks/update-check.sh 2>/dev/null || true)"
case "$out" in *"доступна версия"*) fail "update-check шумит на собственной версии" ;; esac
[ -f "$T/.claude/skills/ingest-confluence/scripts/convert.py" ] || fail "нет конвертера"
[ -f "$T/.claude/skills/ingest-confluence/scripts/fix_tables.py" ] || fail "нет постпроцессора таблиц"
# Инструменты обязаны работать со свежей установки, не только из репо.
( cd "$T" && python3 .claude/skills/link-check/scripts/link_check.py spec >/dev/null ) \
  || fail "link_check не отрабатывает на свежей установке"
( cd "$T" && python3 -c "import sys; sys.path.insert(0,'.claude/skills/ingest-confluence/scripts'); import tablemd" ) \
  || fail "tablemd не импортируется"
[ -f "$T/loft/LICENSE" ] && [ -f "$T/loft/README.ru.md" ] \
  && [ -f "$T/loft/docs/ru/why-loft.md" ] && [ -f "$T/loft/docs/en/why-loft.md" ] \
  || fail "доки/лицензия не уехали в архив"
rm -rf "$T"

echo "собрано: $TGZ"
echo "         ${TGZ}.sha256"
echo "получатель проверяет: shasum -c loft_${VER}.tgz.sha256  (рядом с tgz)"
