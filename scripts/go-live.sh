#!/bin/zsh
# Put the suite live on this Mac mini and eventcaliber.com live on Cloudflare, then check both.
# Run ON the Mini, as yourself (not with sudo), from the repo, after `git pull`:
#
#   scripts/go-live.sh
#
# Safe to run again: every step that is already done is skipped or refreshed. Run it again to
# redeploy the site, for instance once photos are cleared. The first time it asks for:
#   - your Mac password (installing the agents as system services)
#   - a dashboard password of your choosing
#   - a sign-in and an Allow click in the browser (Cloudflare, the account that holds eventcaliber.com)
# It never prints a secret. Every agent stays in dry run: nothing posts or sends because of this.
set -euo pipefail
HERE="${0:A:h}"; REPO="${HERE:h}"; cd "$REPO"
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

say()  { print -P "%F{green}==>%f $*"; }
warn() { print -P "%F{yellow}!!%f $*"; }
stop() { print -P "%F{red}STOP%f $*"; exit 1; }
py()   { .venv/bin/python -c "$@"; }

# 0/1: is a key set in the process environment, .env or the Keychain (the suite's own lookup)
have() { py 'import sys; from convention_social.core import secrets; sys.exit(0 if secrets.get_secret(sys.argv[1]) else 1)' "$1"; }
# the value on stdout, for a pipe only; never echo it to the terminal
value() { py 'import sys; from convention_social.core import secrets; sys.stdout.write(secrets.get_secret(sys.argv[1]) or "")' "$1"; }
setenv() { py 'import sys; from convention_social.core import config; config.write_env({sys.argv[1]: sys.argv[2]})' "$1" "$2"; }

[[ $EUID -ne 0 ]] || stop "run this as yourself, without sudo; it asks for sudo only when it needs it"

# ---------------------------------------------------------------- 1. the suite on this Mini
say "1/4  the suite: packages, database, typefaces and the full test run"
scripts/setup.sh --no-load

if ! have DASHBOARD_PASSWORD_HASH; then
  say "choose a password for the dashboard (8 characters or more; it is stored only as a hash)"
  bin/ccs hash-password --save
fi
have DASHBOARD_PASSWORD_HASH || stop "no dashboard password was saved; run this again"

say "installing the agents as system services (your Mac password)"
sudo "$REPO/scripts/install-daemons.sh"

# ---------------------------------------------------------------- 2. Cloudflare
say "2/4  Cloudflare"
command -v npx >/dev/null || stop "Node is not installed. Install it with:  brew install node   then run this again."
WR=(npx --yes wrangler@4.149.0)
DOMAIN="$(py 'from convention_social.core import config; print(config.get_config().brand_domain)')"

if ! "${WR[@]}" whoami --json >/dev/null 2>&1; then
  say "sign in to Cloudflare: a browser opens; use the account that holds $DOMAIN and click Allow"
  "${WR[@]}" login
  "${WR[@]}" whoami --json >/dev/null 2>&1 || stop "Cloudflare sign-in did not complete; run this again"
fi

if [[ -z "${CLOUDFLARE_ACCOUNT_ID:-}" ]]; then
  accounts=("${(@f)$("${WR[@]}" whoami --json 2>/dev/null | py '
import json, sys
t = sys.stdin.read()
for a in json.loads(t[t.index("{"):]).get("accounts") or []:
    print(a.get("id", "") + "\t" + a.get("name", ""))')}")
  accounts=(${accounts:#})
  if (( ${#accounts} == 0 )); then
    stop "this Cloudflare sign-in has no account; sign in with the one that holds $DOMAIN (${WR[*]} logout, then run this again)"
  elif (( ${#accounts} == 1 )); then
    export CLOUDFLARE_ACCOUNT_ID="${accounts[1]%%$'\t'*}"
  else
    say "this sign-in reaches more than one Cloudflare account; which one holds $DOMAIN?"
    i=0; for a in "${accounts[@]}"; do (( ++i )); print "    $i) ${a#*$'\t'}"; done
    read "pick?number: "
    [[ "$pick" == <-> ]] && (( pick >= 1 && pick <= ${#accounts} )) || stop "not one of the numbers shown"
    export CLOUDFLARE_ACCOUNT_ID="${accounts[$pick]%%$'\t'*}"
  fi
fi

if "${WR[@]}" r2 bucket info eventcaliber-media >/dev/null 2>&1; then
  say "image bucket eventcaliber-media: already there"
else
  say "creating the image bucket eventcaliber-media"
  "${WR[@]}" r2 bucket create eventcaliber-media --update-config=false || stop "Cloudflare would not create the bucket. If R2 is not
     turned on for this account yet: Cloudflare dashboard, R2 Object Storage, and follow its steps (it asks
     for a payment card even for the free allowance; that choice is yours). Then run this again."
fi

d1_id() {
  "${WR[@]}" d1 list --json 2>/dev/null | py '
import json, sys
t = sys.stdin.read()
rows = json.loads(t[t.index("["):]) if "[" in t else []
print(next((r.get("uuid", "") for r in rows if r.get("name") == "eventcaliber-booking"), ""))'
}
DB_ID="$(d1_id)"
if [[ -z "$DB_ID" ]]; then
  say "creating the booking database eventcaliber-booking"
  "${WR[@]}" d1 create eventcaliber-booking --update-config=false || stop "Cloudflare would not create the booking database"
  DB_ID="$(d1_id)"
fi
[[ "$DB_ID" =~ '^[0-9a-f-]{36}$' ]] || stop "could not read the booking database's id from Cloudflare"
say "booking database eventcaliber-booking: ready"

# the deploy config: the committed wrangler.jsonc with the real database id (wrangler.live.jsonc is not
# tracked); read from git so an edit wrangler made to the working copy never reaches the deploy
git show HEAD:wrangler.jsonc | py '
import sys
src = sys.stdin.read()
assert src.count("SET_AFTER_d1_create") == 1, "wrangler.jsonc no longer has its placeholder"
open("wrangler.live.jsonc", "w").write(src.replace("SET_AFTER_d1_create", sys.argv[1]))' "$DB_ID"
LIVE=(-c wrangler.live.jsonc)
"${WR[@]}" d1 execute eventcaliber-booking --remote --file worker/schema.sql -y "${LIVE[@]}" >/dev/null \
  || stop "the booking tables could not be created"
say "booking tables: in place"

# ---------------------------------------------------------------- 3. the site
say "3/4  eventcaliber.com"
if ! have MEDIA_UPLOAD_TOKEN; then
  setenv MEDIA_UPLOAD_TOKEN "$(py 'import secrets; print(secrets.token_hex(32))')"
  say "made a new upload token for the Mini and the site (kept in .env, never shown)"
fi
have MEDIA_BASE_URL || setenv MEDIA_BASE_URL "https://$DOMAIN/m"

bin/ccs site build
"${WR[@]}" deploy "${LIVE[@]}" || stop "the deploy did not go through. If it says the domain already has DNS
     records: Cloudflare, $DOMAIN, DNS, delete the old A, AAAA or CNAME records for $DOMAIN and www (keep
     MX and TXT, they carry the mail), then run this again."
value MEDIA_UPLOAD_TOKEN | "${WR[@]}" secret put UPLOAD_TOKEN "${LIVE[@]}" >/dev/null \
  || stop "the upload token could not be given to the site"
if have NTFY_TOPIC; then
  value NTFY_TOPIC | "${WR[@]}" secret put NTFY_TOPIC "${LIVE[@]}" >/dev/null || warn "the phone push topic was not set on the site"
fi
say "deployed; the site and the Mini share the upload token"

# ---------------------------------------------------------------- 4. check, from the outside
say "4/4  checking (a new domain can take a few minutes to get its certificate)"
SITE_OK=1; bin/ccs site check --wait 600 || SITE_OK=0
PORT="$(py 'from convention_social.core import config; print(config.get_config().dashboard_port)')"
code="$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$PORT/login" || true)"
if [[ "$code" == 200 ]]; then DASH_OK=1; say "dashboard answers on 127.0.0.1:$PORT"; else DASH_OK=0; warn "dashboard did not answer on 127.0.0.1:$PORT (got ${code:-nothing})"; fi
bin/ccs status

print
if (( SITE_OK && DASH_OK )); then
  say "LIVE: https://$DOMAIN and the dashboard. Every agent is in dry run until you switch it on (Agents page)."
  print "    Your phone: run  tailscale serve --bg $PORT  on this Mini and open the address it prints."
else
  stop "not everything passed; the FAIL and !! lines above say what. Fix that, then run this again."
fi
