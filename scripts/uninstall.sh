#!/bin/zsh
# Stop and remove this suite's launchd services. The data root, the database and .env are left untouched.
#   sudo scripts/uninstall.sh
set -u
PREFIX="com.chriskennedyimages.conventionsocial."
ME="${SUDO_USER:-$USER}"
MY_HOME="$(dscl . -read "/Users/$ME" NFSHomeDirectory 2>/dev/null | awk '{print $2}')"; MY_HOME="${MY_HOME:-$HOME}"

# any copy loaded in the user's own session (none is installed there, but never leave one running)
for p in "$MY_HOME"/Library/LaunchAgents/${PREFIX}*.plist(N); do
  label="${p:t:r}"
  launchctl bootout "gui/$(id -u "$ME")/$label" 2>/dev/null && echo "stopped $label (user session)"
  rm -f "$p" && echo "removed $p"
done

daemons=(/Library/LaunchDaemons/${PREFIX}*.plist(N))
if (( ${#daemons} > 0 )); then
  if [[ $EUID -eq 0 ]]; then
    for p in "${daemons[@]}"; do
      label="${p:t:r}"
      launchctl bootout "system/$label" 2>/dev/null && echo "stopped $label"
      rm -f "$p" && echo "removed $p"
    done
  else
    echo "the system daemons are still installed; remove them with:  sudo scripts/uninstall.sh"
    exit 1
  fi
fi
echo "done. The data root and .env were not touched."
