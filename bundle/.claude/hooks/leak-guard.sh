#!/usr/bin/env bash
# PreToolUse leak guard (contract rule 8): deny any write whose content
# contains a .secrets.env value. Safe — only the never-intended case is
# blocked; dormant when .secrets.env is absent. Full hook JSON on stdin.
# Matcher (settings.json): Write|Edit|NotebookEdit.
# Bash is intentionally NOT matched — command-side leaks are review territory.
set -uo pipefail
HOOK_DIR="$(cd "$(dirname "$0")" && pwd -P)"

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

leak=""
while IFS= read -r line || [ -n "$line" ]; do
  case "$line" in ''|\#*) continue ;; esac
  case "$line" in *=*) ;; *) continue ;; esac
  val="${line#*=}"
  # strip surrounding quotes so quoted dotenv values match their runtime form
  case "$val" in
    \"*\") val="${val#\"}"; val="${val%\"}" ;;
    \'*\') val="${val#\'}"; val="${val%\'}" ;;
  esac
  [ -z "$val" ] && continue
  if printf '%s' "$payload" | grep -qF -- "$val"; then
    leak="${line%%=*}"
    break
  fi
done < "$SECRETS"

if [ -n "$leak" ]; then
  printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"Blocked: this write contains the value of secret %s. Reference {{secret:%s}} instead (contract rule 8)."}}\n' "$leak" "$leak"
  exit 0
fi
echo '{}'
exit 0
