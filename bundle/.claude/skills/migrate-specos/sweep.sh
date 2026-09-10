#!/usr/bin/env bash
# Уборка машинерии specos/skillforge из проекта, который теперь ведёт loft.
#
#   bash .claude/skills/migrate-specos/sweep.sh            # только отчёт
#   bash .claude/skills/migrate-specos/sweep.sh --apply    # карантин
#
# Переносится ТОЛЬКО машинерия. Состояние проекта (wiki/, spec/, docs/,
# memory/, BACKLOG, QUESTIONS, .secrets.env) не трогается никогда.
# Ничего не удаляется: всё уезжает в .loft-migration/<ts>/ с MANIFEST.md,
# где каждая строка — команда mv для отката.
set -uo pipefail
PROJECT="${CLAUDE_PROJECT_DIR:-$PWD}"
cd "$PROJECT" || exit 1
APPLY=0
[ "${1:-}" = "--apply" ] && APPLY=1

# Машинерия: бандлы, дистрибутивы и служебное состояние движков specos/skillforge.
MACHINERY=()
for p in specos skillforge; do [ -d "$p" ] && MACHINERY+=("$p"); done
for f in specos-*.tar.gz specos-*.tar.gz.sha256 skillforge_*.tgz skillforge_*.tgz.sha256; do
  [ -f "$f" ] && MACHINERY+=("$f")
done
for f in .data/.specos-* .data/runs.jsonl .data/memory-index.json; do
  [ -e "$f" ] && MACHINERY+=("$f")
done
[ -d .data/bin ] && ls .data/bin/specos-* >/dev/null 2>&1 && MACHINERY+=(".data/bin")
[ -d .data/backup ] && MACHINERY+=(".data/backup")

# Неоднозначное: показываем, решает владелец — скрипт не гадает о чужих файлах.
FLAGGED=()
[ -d "доработка" ] && FLAGGED+=("доработка/ — временный хак chat-render? посмотреть и решить")
[ -d .specweave ] && FLAGGED+=(".specweave/ — кэш specweave (26МБ sqlite); восстановим при разморозке v2 переиндексацией")
# Бэкапы .claude: интересны только чужие. Свой бэкап от переустановки loft
# (внутри лежит .claude/VERSION ядра) памяти specos не содержит — помечать
# его каждый раз значит приучать владельца пролистывать FLAGGED не читая.
for b in .claude.bak.*; do
  [ -d "$b" ] || continue
  if [ ! -f "$b/VERSION" ] || grep -qs 'specos-managed' "$b/CLAUDE.md"; then
    FLAGGED+=("$b — бэкап прежнего .claude; внутри может жить память specos (memory/knowledge) — ценное перенести скиллом remember, потом решить судьбу")
  fi
done
# .mcp.json: specos'овским считается конфиг, где сам сервер specos'овский —
# имя сервера со словом specos или путь запуска с компонентом specos
# (specos/, .specos/, specos-0.8/). Грепа по слову мало: «мигрировано со
# specos» в комментарии или в env — это чужой рабочий конфиг, а не остаток.
# Разбор — тот же, что в install.sh (mcp_kind); держать в синхроне с ним.
mcp_kind() {
  python3 - "$1" <<'PY' 2>/dev/null
import json, sys
try:
    d = json.load(open(sys.argv[1], encoding="utf-8"))
except Exception:
    sys.exit(2)
srv = d.get("mcpServers")
if not isinstance(srv, dict):
    sys.exit(2)

def specos_path(value):
    for comp in str(value).replace("\\", "/").split("/"):
        c = comp.lower()
        if c in ("specos", ".specos") or c.startswith(("specos-", "specos_", "specos.")):
            return True
    return False

for name, cfg in srv.items():
    if "specos" in str(name).lower():
        print("specos"); sys.exit(0)
    values = []
    if isinstance(cfg, dict):
        for key in ("command", "cwd", "url"):
            if cfg.get(key) is not None:
                values.append(cfg[key])
        args = cfg.get("args")
        if isinstance(args, list):
            values += args
        env = cfg.get("env")
        if isinstance(env, dict):
            values += list(env.keys())
    else:
        values.append(cfg)
    for v in values:
        if specos_path(v):
            print("specos"); sys.exit(0)
print("other")
PY
}
if [ -f .mcp.json ]; then
  case "$(mcp_kind .mcp.json || true)" in
    specos)
      FLAGGED+=(".mcp.json — всё ещё содержит specos-серверы (инсталлер обычно уводит его в бэкап; проверь)") ;;
    other) : ;;
    *)
      FLAGGED+=(".mcp.json — не разобран (битый JSON или нестандартная схема); если это конфиг specos — убрать руками") ;;
  esac
fi

# bash 3.2 (macOS) под set -u ругается на "${A[@]}" пустого массива —
# отсюда форма ${A[@]+"${A[@]}"} везде, где массив может быть пуст.
echo "== sweep: $PROJECT =="
if [ "${#MACHINERY[@]}" -gt 0 ]; then
  echo "MACHINERY (${#MACHINERY[@]}) — уедет в карантин при --apply:"
  printf '  %s\n' ${MACHINERY[@]+"${MACHINERY[@]}"}
else
  echo "MACHINERY (0) — машинерии specos/skillforge не найдено"
fi
if [ "${#FLAGGED[@]}" -gt 0 ]; then
  echo "FLAGGED (${#FLAGGED[@]}) — остаётся на месте, решает владелец:"
  printf '  %s\n' ${FLAGGED[@]+"${FLAGGED[@]}"}
fi

[ "$APPLY" -eq 1 ] || exit 0
[ "${#MACHINERY[@]}" -gt 0 ] || { echo "нечего переносить"; exit 0; }

TS="$(date +%Y%m%d%H%M%S)"
Q=".loft-migration/$TS"
mkdir -p "$Q"
MANIFEST="$Q/MANIFEST.md"
{
  echo "# Карантин specos-машинерии от $TS"
  echo
  echo "Откат любой строки: выполнить её команду из корня проекта."
  echo
} > "$MANIFEST"
# Строка отката несёт свой mkdir -p: к моменту отката родительского каталога
# может уже не быть (пустой .data/ убрали руками), и голый mv тогда падает.
for p in ${MACHINERY[@]+"${MACHINERY[@]}"}; do
  dest="$Q/$(dirname "$p")"
  mkdir -p "$dest"
  mv "$p" "$dest/" || { echo "FAIL: не перенеслось: $p"; exit 1; }
  echo "- \`mkdir -p '$(dirname "$p")' && mv '$Q/$p' '$p'\` — было: $p" >> "$MANIFEST"
done
echo "перенесено: ${#MACHINERY[@]} → $Q (манифест: $MANIFEST)"

# Ре-аудит переживает сессию строкой в очереди, а не чьей-то памятью.
if [ -f BACKLOG.md ] && ! grep -q "src:migrate-specos" BACKLOG.md; then
  printf -- '- P1 | корпус | Ре-аудит после миграции со specos: tz-audit + перенос ценного из .claude.bak (memory/knowledge) в memory/ | ev:%s | src:migrate-specos\n' "$MANIFEST" >> BACKLOG.md
  echo "в BACKLOG.md добавлена строка ре-аудита"
fi
exit 0
