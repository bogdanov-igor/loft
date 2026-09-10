# Самотесты loft — 05-bundle. Подключается из test/run.sh; переменные REPO/SK/HK/TMP
# и функции ok/bad/has/hasnt/section приходят оттуда.
#
# Целостность бандла: то, что читает не человек, а харнесс Claude Code —
# фронтматтер скиллов и агентов, settings.json, пути хуков, поля model/effort/
# disallowedTools. Ошибка здесь не падает при прогоне: скилл просто молча не
# грузится, агент молча получает не ту модель. Отсюда отдельный кейс.
#
# Разбор — только stdlib python3 (PyYAML в ядре нет и не будет): фронтматтер
# бандла плоский — `key: value` плюс списки `- item`, этого достаточно.
# Питон печатает по строке на утверждение (`ok|…` / `fail|…`), bash их считает,
# поэтому счётчик и формат отказов общие с остальными кейсами.

section "bundle — целостность ядра"
python3 - "$REPO/bundle/.claude" > "$TMP/bundle.report" 2> "$TMP/bundle.err" <<'PY'
import json, os, re, shlex, sys

ROOT = sys.argv[1]                    # bundle/.claude
BUNDLE = os.path.dirname(ROOT)        # bundle/ — корень «проекта» для .claude/…

def ok(msg):  sys.stdout.write("ok|%s\n" % msg)
def bad(msg): sys.stdout.write("fail|%s\n" % " ".join(str(msg).split()))
def check(cond, msg): ok(msg) if cond else bad(msg)

def unquote(v):
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        return v[1:-1]
    return v

def frontmatter(path):
    """Плоский фронтматтер: `key: value` и списки `- item`.
    Возвращает (данные, порядок ключей, ошибка)."""
    try:
        lines = open(path, encoding="utf-8").read().split("\n")
    except OSError as e:
        return None, None, "не читается: %s" % e
    if not lines or lines[0].strip() != "---":
        return None, None, "фронтматтер не открывается строкой ---"
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        return None, None, "фронтматтер не закрывается строкой ---"
    data, keys, cur = {}, [], None
    for raw in lines[1:end]:
        s = raw.rstrip()
        if not s.strip() or s.lstrip().startswith("#"):
            continue
        if s.lstrip().startswith("- "):
            if cur is None:
                return None, None, "элемент списка до первого ключа"
            item = unquote(s.lstrip()[2:])
            if isinstance(data[cur], list):
                data[cur].append(item)
            elif data[cur] == "":
                data[cur] = [item]
            else:
                return None, None, "у ключа %s разом значение и список" % cur
            continue
        m = re.match(r"^([A-Za-z][A-Za-z0-9_-]*):\s*(.*)$", s)
        if not m:
            return None, None, "строка не разбирается как `key: value`: %s" % s.strip()
        cur = m.group(1)
        if cur in data:
            return None, None, "ключ %s повторяется" % cur
        keys.append(cur)
        data[cur] = unquote(m.group(2))
    return data, keys, None

def flat(v):
    """Значение как одна строка — для поиска подстрок в списке или скаляре."""
    return " ".join(v) if isinstance(v, list) else ("" if v is None else str(v))

def items(v):
    """Значение как список: список YAML или скаляр через запятую."""
    if isinstance(v, list):
        return [x.strip() for x in v if x.strip()]
    if v is None or not str(v).strip():
        return []
    return [x.strip() for x in str(v).split(",") if x.strip()]

def text_of(path):
    return open(path, encoding="utf-8").read()

# ── settings.json ──────────────────────────────────────────────────────────
sp = os.path.join(ROOT, "settings.json")
settings = None
try:
    settings = json.load(open(sp, encoding="utf-8"))
    ok("settings.json — валидный JSON")
except Exception as e:
    bad("settings.json — не разбирается: %s" % e)

if isinstance(settings, dict):
    check(settings.get("autoMemoryEnabled") is False,
          "settings.json: autoMemoryEnabled есть и false (память ядра — memory/, не встроенная)")
    hooks = settings.get("hooks")
    check(isinstance(hooks, dict) and hooks, "settings.json: секция hooks непуста")
    seen = 0
    hooks_dir = os.path.realpath(os.path.join(ROOT, "hooks"))
    for event, groups in (hooks or {}).items():
        if not isinstance(groups, list):
            bad("settings.json: %s — не список групп" % event)
            continue
        for group in groups:
            for h in (group or {}).get("hooks", []):
                seen += 1
                where = "%s[%d]" % (event, seen)
                check(h.get("type") == "command", "settings.json: %s — type: command" % where)
                cmd = h.get("command") or ""
                try:
                    tokens = shlex.split(cmd)
                except ValueError:
                    tokens = []
                if not tokens:
                    bad("settings.json: %s — пустая команда" % where)
                    continue
                p = tokens[0].replace("${CLAUDE_PROJECT_DIR}", BUNDLE)
                p = p.replace("$CLAUDE_PROJECT_DIR", BUNDLE)
                rp = os.path.realpath(p)
                if not os.path.isfile(rp):
                    bad("settings.json: %s — команда указывает на несуществующий файл: %s" % (where, tokens[0]))
                    continue
                check(rp.startswith(hooks_dir + os.sep),
                      "settings.json: %s — хук лежит в .claude/hooks/ (%s)" % (where, os.path.basename(rp)))
                runnable = os.access(rp, os.X_OK)
                if not runnable:
                    with open(rp, "rb") as fh:
                        runnable = fh.read(2) == b"#!"
                check(runnable, "settings.json: %s — %s исполняемый или с shebang" % (where, os.path.basename(rp)))
    check(seen > 0, "settings.json: хуки перечислены")

# ── скиллы ─────────────────────────────────────────────────────────────────
# Набор ключей фронтматтера скилла, известных Claude Code. Неизвестный ключ —
# опечатка, которая не сработает молча (harness её игнорирует).
SKILL_KEYS = set("""name description when_to_use argument-hint arguments
disable-model-invocation user-invocable allowed-tools disallowed-tools model
effort context agent background hooks paths shell metadata license
compatibility""".split())
# Скиллы, которые агент не зовёт сам, — только по прямой команде владельца.
# Это решение владельца; меняется список — правится и тест.
NO_AUTO = set(["claude-docs", "deliver-pdf", "migrate-specos"])

skills_dir = os.path.join(ROOT, "skills")
skills = sorted(d for d in os.listdir(skills_dir) if os.path.isdir(os.path.join(skills_dir, d)))
check(len(skills) >= 15, "скиллов в бандле не меньше 15 (нашлось %d)" % len(skills))

no_auto_found = set()
for d in skills:
    p = os.path.join(skills_dir, d, "SKILL.md")
    if not os.path.isfile(p):
        bad("skills/%s: нет SKILL.md" % d)
        continue
    fm, keys, err = frontmatter(p)
    if err:
        bad("skills/%s: %s" % (d, err))
        continue
    ok("skills/%s: фронтматтер открыт и закрыт ---" % d)
    name = fm.get("name")
    check(name == d, "skills/%s: name совпадает с именем каталога (name: %s)" % (d, name))
    check(isinstance(name, str) and re.match(r"^[a-z0-9]+(-[a-z0-9]+)*$", name or ""),
          "skills/%s: name только из [a-z0-9-] (name: %s)" % (d, name))
    desc = fm.get("description")
    if not isinstance(desc, str) or not desc.strip() or desc.strip() in ("|", ">", "|-", ">-", "|+", ">+"):
        bad("skills/%s: description непустой и в одну строку" % d)
    else:
        ok("skills/%s: description непустой и в одну строку" % d)
        check(len(desc) <= 1024, "skills/%s: description ≤ 1024 символов (сейчас %d)" % (d, len(desc)))
    unknown = [k for k in (keys or []) if k not in SKILL_KEYS]
    check(not unknown, "skills/%s: во фронтматтере только известные ключи (лишние: %s)" % (d, ", ".join(unknown)))
    for m in re.finditer(r"Bash\(python3\s+([^\s)]+)", flat(fm.get("allowed-tools"))):
        rel = m.group(1)
        check(os.path.isfile(os.path.join(BUNDLE, rel)),
              "skills/%s: allowed-tools ссылается на существующий скрипт %s" % (d, rel))
    if str(fm.get("disable-model-invocation", "")).lower() == "true":
        no_auto_found.add(d)
check(no_auto_found == NO_AUTO,
      "disable-model-invocation ровно у %s (сейчас: %s)"
      % (", ".join(sorted(NO_AUTO)), ", ".join(sorted(no_auto_found)) or "ни у кого"))

# ── агенты ─────────────────────────────────────────────────────────────────
AGENT_KEYS = set("""name description tools disallowedTools model effort
permissionMode skills memory mcpServers maxTurns background isolation hooks
color""".split())
MODELS = set(["opus", "sonnet", "haiku", "fable", "inherit"])
EFFORTS = set(["low", "medium", "high", "xhigh", "max"])

agents_dir = os.path.join(ROOT, "agents")
agents = sorted(f for f in os.listdir(agents_dir) if f.endswith(".md"))
check(set(a[:-3] for a in agents) == set(["scout", "verifier"]),
      "агенты бандла — scout и verifier (сейчас: %s)" % ", ".join(a[:-3] for a in agents))

fms = {}
for f in agents:
    stem = f[:-3]
    fm, keys, err = frontmatter(os.path.join(agents_dir, f))
    if err:
        bad("agents/%s: %s" % (f, err))
        continue
    fms[stem] = fm
    ok("agents/%s: фронтматтер открыт и закрыт ---" % f)
    check(fm.get("name") == stem, "agents/%s: name совпадает с именем файла (name: %s)" % (f, fm.get("name")))
    unknown = [k for k in (keys or []) if k not in AGENT_KEYS]
    check(not unknown, "agents/%s: во фронтматтере только известные ключи (лишние: %s)" % (f, ", ".join(unknown)))
    model = str(fm.get("model", ""))
    check(model in MODELS or model.startswith("claude-"),
          "agents/%s: model из известных или полный id claude-… (model: %s)" % (f, model or "нет"))
    if "effort" in fm:
        check(str(fm["effort"]) in EFFORTS,
              "agents/%s: effort из %s (effort: %s)" % (f, "/".join(sorted(EFFORTS)), fm["effort"]))

scout = fms.get("scout")
if scout is None:
    bad("agents/scout.md: фронтматтер не разобрался — проверки scout пропущены")
else:
    check(scout.get("model") == "sonnet", "scout: model sonnet (разведка не стоит опуса)")
    dis = items(scout.get("disallowedTools"))
    for t in ("Write", "Edit", "NotebookEdit"):
        check(t in dis, "scout: disallowedTools содержит %s (scout ничего не меняет)" % t)
    tools = items(scout.get("tools"))
    for t in ("Write", "Edit", "NotebookEdit"):
        check(t not in tools, "scout: %s нет в tools" % t)
verifier = fms.get("verifier")
if verifier is None:
    bad("agents/verifier.md: фронтматтер не разобрался — проверки verifier пропущены")
else:
    check(verifier.get("model") == "opus", "verifier: model opus (вердикт судит опус)")

# ── output-style ───────────────────────────────────────────────────────────
osp = os.path.join(ROOT, "output-styles", "analyst.md")
fm, keys, err = frontmatter(osp)
if err:
    bad("output-styles/analyst.md: %s" % err)
else:
    ok("output-styles/analyst.md: фронтматтер открыт и закрыт ---")
    check(fm.get("name") == "analyst", "output-styles/analyst.md: name analyst (name: %s)" % fm.get("name"))
    check(str(fm.get("keep-coding-instructions", "")).lower() == "false",
          "output-styles/analyst.md: keep-coding-instructions false (ядро пишет документы, не код)")

# ── текстовые запреты в скиллах и агентах ──────────────────────────────────
# Номер правила контракта протухает при первой же перенумерации; git — граница
# ядра (решение владельца: инструментов git ядро не касается).
BANNED = [
    (re.compile(r"правил[а-яё]*\s*№?\s*\d", re.I), "ссылка на номер правила контракта"),
    (re.compile(r"\brule\s+\d", re.I), "ссылка на номер правила контракта (rule N)"),
    (re.compile(r"(?<![a-zA-Z0-9-])git(?![a-zA-Z0-9-])", re.I), "слово git"),
]
prose = [os.path.join(skills_dir, d, "SKILL.md") for d in skills]
prose += [os.path.join(agents_dir, f) for f in agents]
prose = [p for p in prose if os.path.isfile(p)]
for rx, what in BANNED:
    hits = []
    for p in prose:
        for n, line in enumerate(text_of(p).split("\n"), 1):
            if rx.search(line):
                hits.append("%s:%d" % (os.path.relpath(p, ROOT), n))
    check(not hits, "в скиллах и агентах нет запрещённого (%s): %s" % (what, ", ".join(hits)))

# ── упоминания скиллов разрешаются в каталоги ──────────────────────────────
# Переименовали скилл, забыли контракт — ссылка на него молча становится ложью.
known = set(skills)
# Дефисный термин в бэктиках, который не скилл: добавить сюда осознанно.
NOT_A_SKILL = set()
claude_md = os.path.join(ROOT, "CLAUDE.md")
missing = []
for p in prose + [claude_md]:
    t = text_of(p)
    for m in re.finditer(r"[Ss]kill[а-яёА-ЯЁa-zA-Z]*\s+`/?([a-z0-9][a-z0-9-]*)`", t):
        if m.group(1) not in known:
            missing.append("%s → %s" % (os.path.relpath(p, ROOT), m.group(1)))
check(not missing, "упоминания «skill `имя`» ведут в существующие каталоги skills/ (мимо: %s)" % ", ".join(missing))

t = text_of(claude_md)
mentioned = set(m.group(1) for m in re.finditer(r"`/([a-z0-9][a-z0-9-]*)`", t))
mentioned |= set(m.group(1) for m in re.finditer(r"`([a-z0-9]+(?:-[a-z0-9]+)+)`", t))
mentioned -= NOT_A_SKILL
missing = sorted(n for n in mentioned if n not in known)
check(not missing, "имена скиллов из CLAUDE.md существуют как каталоги (мимо: %s)" % ", ".join(missing))
check(len(mentioned & known) >= 8,
      "контракт вообще ссылается на скиллы (нашлось %d)" % len(mentioned & known))
PY
if [ -s "$TMP/bundle.err" ]; then
  bad "разбор бандла упал: $(tr '\n' ' ' < "$TMP/bundle.err" | tail -c 200)"
fi
[ -s "$TMP/bundle.report" ] || bad "разбор бандла не выдал ни одного утверждения"
while IFS= read -r line; do
  case "$line" in
    "ok|"*) ok ;;
    *)      bad "${line#fail|}" ;;
  esac
done < "$TMP/bundle.report"
