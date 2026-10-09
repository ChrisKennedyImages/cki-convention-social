#!/bin/zsh
# One-shot, re-runnable install. Run ON the Mac mini as the login user (not with sudo).
#   scripts/setup.sh            venv, .env, data root, database, tests, then install the services
#                               (asks for your password once, for scripts/install-daemons.sh)
#   scripts/setup.sh --no-load  everything except installing the services (dev machines)
set -euo pipefail
HERE="${0:A:h}"; REPO="${HERE:h}"; cd "$REPO"
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
LOAD=1; [[ "${1:-}" == "--no-load" ]] && LOAD=0

say() { print -P "%F{green}==>%f $*"; }
warn() { print -P "%F{yellow}!!%f $*"; }

if [[ $EUID -eq 0 ]]; then echo "run this as yourself, without sudo; it asks for sudo only when it needs it"; exit 1; fi

# Python 3.13 or newer, from Homebrew (Apple Silicon or Intel prefix)
PY=""
for cand in /opt/homebrew/bin/python3.13 /usr/local/bin/python3.13 /opt/homebrew/bin/python3 /usr/local/bin/python3; do
  if [[ -x "$cand" ]] && "$cand" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 13) else 1)' 2>/dev/null; then PY="$cand"; break; fi
done
[[ -n "$PY" ]] || { echo "Python 3.13+ not found in /opt/homebrew/bin or /usr/local/bin. Install with: brew install python@3.13"; exit 1; }
say "python: $("$PY" --version) ($PY)"

if [[ ! -d .venv ]]; then say "creating .venv"; "$PY" -m venv .venv; fi
say "installing requirements"; .venv/bin/pip install -q --upgrade pip; .venv/bin/pip install -q -r requirements.txt

if [[ ! -f .env ]]; then
  cp .env.example .env; chmod 600 .env
  warn "created .env from .env.example; fill it in (bin/ccs env-check shows what is missing)"
fi

# data root: the environment, else CCS_DATA_ROOT in .env, else the default; a leading ~ means this home
DATA="${CCS_DATA_ROOT:-}"
if [[ -z "$DATA" ]]; then DATA="$(sed -n 's/^CCS_DATA_ROOT=//p' .env | tail -n 1 | tr -d '"'"'"'')"; fi
[[ -n "$DATA" ]] || DATA="$HOME/cki-convention-social-data"
[[ "$DATA" == "~"* ]] && DATA="$HOME${DATA#\~}"
export CCS_DATA_ROOT="$DATA"
say "data root: $DATA"; mkdir -p "$DATA"
say "database"; bin/ccs init-db | sed 's/^/    /'
say "brand typefaces"; bin/ccs fonts | sed "s/^/    /"
say "tests"; bin/test | tail -n 3 | sed 's/^/    /'

if (( LOAD )); then
  say "installing the services as system daemons (your password, once)"
  sudo "$REPO/scripts/install-daemons.sh"
  say "status"; bin/ccs status | sed 's/^/    /'
  say "dashboard: http://127.0.0.1:$(sed -n 's/^DASHBOARD_PORT=//p' .env | tail -n 1 | grep . || echo 4610)  (password: bin/ccs hash-password, then .env)"
else
  warn "services not installed (--no-load). Install later with: sudo scripts/install-daemons.sh"
fi
say "done. Every agent that sends or publishes is in DRY RUN until you switch it on from the dashboard's Agents page."
