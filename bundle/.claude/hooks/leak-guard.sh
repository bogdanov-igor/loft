#!/usr/bin/env bash
# PreToolUse leak guard (contract rule 8): deny any write whose NEW content
# contains a .secrets.env value. Safe — only the never-intended case is
# blocked; dormant when .secrets.env is absent. Full hook JSON on stdin.
# Matcher (settings.json): Write|Edit|NotebookEdit.
# Bash is intentionally NOT matched — command-side leaks are review territory.
#
# What is scanned: only the text being written — Write.content, Edit.new_string
# (MultiEdit: every edits[].new_string), NotebookEdit.new_source. Scanning the
# whole payload blocked the edit that REMOVES a leaked secret, because the value
# still sits in old_string. python3 does the JSON parsing: it ships wherever the
# core does (the converters need it). If it fails, we fall back to the raw
# payload — noisier, never quieter.
#
# What counts as a secret: a .secrets.env value of 6 characters or more. Shorter
# values (PORT=8080, USER=admin) match any number or word in any document and
# would make the hook a nuisance instead of a guard.
set -uo pipefail
HOOK_DIR="$(cd "$(dirname "$0")" && pwd -P)"
MINLEN=6

# Project root: the harness sets CLAUDE_PROJECT_DIR for hook invocations.
# Manual runs fall back to the physical up-walk (hooks -> .claude -> project).
if [ -n "${CLAUDE_PROJECT_DIR:-}" ] && [ -d "$CLAUDE_PROJECT_DIR" ]; then
  HOST="$(cd "$CLAUDE_PROJECT_DIR" && pwd -P)"
else
  HOST="$(cd "$HOOK_DIR/../.." && pwd -P)"
fi
SECRETS="${LOFT_SECRETS_FILE:-$HOST/.secrets.env}"

payload="$(cat)"
[ -s "$SECRETS" ] || { echo '{}'; exit 0; }

# JSON string escaping — for the answer (a key may carry a quote or a
# backslash) and for the fallback comparison against the raw payload.
json_escape() {
  local s="$1"
  s="${s//\\/\\\\}"
  s="${s//\"/\\\"}"
  s="${s//$'\t'/\\t}"
  s="${s//$'\n'/\\n}"
  s="${s//$'\r'/\\r}"
  printf '%s' "$s"
}

if subject="$(printf '%s' "$payload" | python3 -c '
import json, sys
try:
    d = json.load(sys.stdin)
except Exception:
    sys.exit(2)
ti = d.get("tool_input")
if not isinstance(ti, dict):
    sys.exit(2)
out = []
found = False
for k in ("content", "new_string", "new_source"):
    if k in ti:
        found = True
        v = ti[k]
        if isinstance(v, list):
            out.append("".join(str(x) for x in v))
        elif v is not None:
            out.append(str(v))
edits = ti.get("edits")
if isinstance(edits, list):
    for it in edits:
        if isinstance(it, dict) and "new_string" in it:
            found = True
            out.append(str(it["new_string"]))
if not found:
    sys.exit(2)
sys.stdout.write("\n".join(out))
' 2>/dev/null)"; then
  :
else
  subject="$payload"   # unparsable payload or unknown tool: scan everything
fi

leak=""
while IFS= read -r line || [ -n "$line" ]; do
  line="${line%$'\r'}"                          # CRLF-authored .secrets.env
  line="${line#"${line%%[![:space:]]*}"}"       # leading whitespace
  case "$line" in ''|\#*) continue ;; esac
  case "$line" in 'export '*) line="${line#export }" ;; esac
  case "$line" in *=*) ;; *) continue ;; esac
  key="${line%%=*}"; val="${line#*=}"
  key="${key%"${key##*[![:space:]]}"}"          # trailing whitespace in key
  val="${val#"${val%%[![:space:]]*}"}"          # leading whitespace in value
  case "$val" in
    # quoted value: everything up to the closing quote, tail (comment) ignored
    \"*) val="${val#\"}"; val="${val%%\"*}" ;;
    \'*) val="${val#\'}"; val="${val%%\'*}" ;;
    *)   case "$val" in *' #'*) val="${val%% #*}" ;; esac   # inline comment
         val="${val%"${val##*[![:space:]]}"}" ;;
  esac
  [ "${#val}" -ge "$MINLEN" ] || continue
  esc="$(json_escape "$val")"
  case "$subject" in
    *"$val"*) leak="$key" ;;
    *"$esc"*) leak="$key" ;;                    # payload seen unparsed
  esac
  [ -n "$leak" ] && break
done < "$SECRETS"

if [ -n "$leak" ]; then
  k="$(json_escape "$leak")"
  printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"Blocked: this write contains the value of secret %s. Reference {{secret:%s}} instead (contract rule 8). Values shorter than %s characters are never treated as secrets."}}\n' \
    "$k" "$k" "$MINLEN"
  exit 0
fi
echo '{}'
exit 0
