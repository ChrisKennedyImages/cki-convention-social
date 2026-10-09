#!/bin/zsh
# Install (or refresh) the services as SYSTEM launchd daemons that run as you.
#
#   sudo scripts/install-daemons.sh
#
# Run scripts/setup.sh first, as yourself: it builds the venv, the .env and the
# database. This script renders launchd/*.plist.template into
# /Library/LaunchDaemons (UserName = the account that ran sudo, so the agents
# use the same files, data folder and .env), and loads them into the system
# domain, which exists whether or not anyone is logged in at the screen.
# Re-run it any time to refresh after `git pull`.
set -euo pipefail

if [[ $EUID -ne 0 ]]; then echo "run with sudo: sudo $0"; exit 1; fi
USER_NAME="${SUDO_USER:-}"
if [[ -z "$USER_NAME" || "$USER_NAME" == "root" ]]; then echo "run via sudo from your own account, not as root directly"; exit 1; fi
USER_HOME="$(dscl . -read "/Users/$USER_NAME" NFSHomeDirectory | awk '{print $2}')"
HERE="${0:A:h}"; REPO="${HERE:h}"
DST="/Library/LaunchDaemons"
PREFIX="com.chriskennedyimages.conventionsocial."
PY="$REPO/.venv/bin/python"

say() { print -P "%F{green}==>%f $*"; }

[[ -x "$PY" ]] || { echo "no venv at $REPO/.venv; run scripts/setup.sh (without sudo) first"; exit 1; }

# data root: CCS_DATA_ROOT passed through sudo, else from the repo's .env, else the default; ~ is the user's home
DATA="${CCS_DATA_ROOT:-}"
if [[ -z "$DATA" && -f "$REPO/.env" ]]; then DATA="$(sed -n 's/^CCS_DATA_ROOT=//p' "$REPO/.env" | tail -n 1 | tr -d '"'"'"'')"; fi
[[ -n "$DATA" ]] || DATA="$USER_HOME/cki-convention-social-data"
[[ "$DATA" == "~"* ]] && DATA="$USER_HOME${DATA#\~}"
mkdir -p "$DATA/logs"
chown "$USER_NAME":staff "$DATA" "$DATA/logs"

templates=("$REPO"/launchd/${PREFIX}*.plist.template(N))
if (( ${#templates} == 0 )); then echo "no templates in $REPO/launchd"; exit 1; fi

say "installing ${#templates} services as system daemons running as $USER_NAME (data: $DATA)"
failed=()
for t in "${templates[@]}"; do
  label="${${t:t}%.plist.template}"
  dst="$DST/$label.plist"
  # never leave a copy loaded in the user's own session as well
  launchctl bootout "gui/$(id -u "$USER_NAME")/$label" 2>/dev/null || true
  launchctl bootout "system/$label" 2>/dev/null || true
  # bootout returns before a running service (the always-on dashboard) has stopped, and loading it
  # again too soon fails with "Bootstrap failed: 5: Input/output error" (the Mini, 2026-10-09):
  # wait until launchd no longer knows the label, then load, with two retries
  for i in {1..30}; do launchctl print "system/$label" >/dev/null 2>&1 || break; sleep 0.5; done
  sed -e "s|__USER__|$USER_NAME|g" -e "s|__REPO__|$REPO|g" -e "s|__PYTHON__|$PY|g" \
      -e "s|__HOME__|$USER_HOME|g" -e "s|__DATA__|$DATA|g" "$t" > "$dst"
  chown root:wheel "$dst"; chmod 644 "$dst"
  plutil -lint -s "$dst" >/dev/null || { echo "bad plist $dst"; exit 1; }
  loaded=0
  for attempt in 1 2 3; do
    if (( attempt < 3 )); then
      launchctl bootstrap system "$dst" 2>/dev/null && { loaded=1; break; }
      sleep 2
    else
      launchctl bootstrap system "$dst" && loaded=1
    fi
  done
  if (( loaded )); then echo "    loaded $label"; else echo "    FAILED to load $label"; failed+=("$label"); fi
done

sleep 2
say "system domain"
for t in "${templates[@]}"; do
  label="${${t:t}%.plist.template}"
  # "running", or "not running" for a scheduled agent between its runs; a label launchd does not
  # know is "not loaded" (never an error that ends this script)
  state="$(launchctl print "system/$label" 2>/dev/null | awk -F' = ' '/^\tstate = /{print $2}')" || true
  echo "    ${state:-not loaded}  $label"
done
if (( ${#failed} )); then
  echo "!! these did not load: ${failed[*]}. Run this again in a minute; if it repeats, see"
  echo "   sudo launchctl print system/<label> and the log in $DATA/logs"
  exit 1
fi
say "done. Stop one:  sudo launchctl bootout system/${PREFIX}publisher"
echo "    Restart one: sudo launchctl kickstart -k system/${PREFIX}dashboard"
echo "    Remove all:  sudo scripts/uninstall.sh"
