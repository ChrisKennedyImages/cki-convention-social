# cki-convention-social: standing instructions for every Claude session

FOUNDER_DECISIONS.md is the source of truth. Read it first.

## Laws

- **Read, don't recall.** Every filename, env key, table, column, module or
  status string you put into code, a command or a claim must come from a
  `grep` / `ls` / `cat` you ran this session.
- **Verify at the consumer.** A thing works when it is proven where it is
  used: a real test post, a real email in Chris's inbox, the dashboard on his
  phone. A check you have not seen fire is not a check.
- **Fail closed.** A gate that cannot run says no. Unknown clearance, an
  unsorted photo, a missing key, a blind spend ledger: all mean "do not
  use, do not send".
- **The photo library is read only.** The suite lists and downloads; it never
  writes to Drive. Only the `drive.readonly` scope is ever requested.
- **People's photos fail closed.** Not cleared by default; the do-not-use list
  is honoured everywhere. No model judges anyone's age: Chris's Approve is the
  check (his ruling, 2026-10-15).
- **No prices, ever, in anything public.** Quote requests only.
- **No affiliation claims** unless Chris confirmed the event.
- **Show first.** Anything visual goes to Chris as a rendered file before it
  is wired. Flags for new surfaces default off.
- **Nothing from another company.** No name, key, account, domain, bucket,
  topic or id from another suite, anywhere (`tests/test_banned_words.py`).
  One exception, Chris's own choice on 2026-10-11: the Anthropic key is the one
  his other suite uses, copied into `.env` with `bin/ccs copy-key` (that suite's
  file is only read; the key never enters the repo).
- **Secrets** live only in the untracked `.env` or the Keychain. Never commit,
  print or repeat them.

## Working in this repo

- Branch per change, pull request, CI green before merge.
- `bin/test` must show 0 failures, 0 errors, 0 skips.
- Runtime data lives in `CCS_DATA_ROOT` (`~/cki-convention-social-data`),
  never in the repo.
- Runtime is the Mac mini, as system LaunchDaemons with the prefix
  `com.chriskennedyimages.conventionsocial.`; the dashboard listens on
  127.0.0.1:4610 and is reached over Tailscale at
  https://mac-mini.tail915d2c.ts.net:8443/
  (`tailscale serve --bg --https=8443 http://127.0.0.1:4610` on the Mini; only devices on
  Chris's Tailscale network can open it). The suite's links use it once
  `DASHBOARD_PUBLIC_URL` is set to it on the Mini (Keys page).
- **The Mini is shared with other suites. Touch only what is ours.** Our launchd
  labels, our port 4610, our `.env`, our data root, Tailscale https port 8443.
  Never https 443 on the Mini's Tailscale name: another suite's dashboard lives
  there. On 2026-10-09 serving port 4610 without `--https=8443` (so on 443) replaced
  it; before any command that changes a machine-wide setting (Tailscale serve,
  wrangler login, Homebrew, launchd outside our prefix), read what is there now
  and leave everything that is not ours exactly as it is.
- Going live and every redeploy: `scripts/go-live.sh` on the Mini. First run
  ended LIVE on 2026-10-09.
- Code reaches the Mini by itself (Chris, 2026-10-11): the updater agent
  tests anything newly merged to `main` with the full suite, then
  fast-forwards and restarts the dashboard. A merge to `main` is therefore a
  deploy: never merge red. New `launchd/` templates still need one
  `scripts/go-live.sh` on the Mini; the updater flags them.

## How changes reach the Mini (Chris, 2026-10-15)

- **One change at a time on the Mini.** Merge one pull request, let the
  updater test and deploy it (`curl -s http://127.0.0.1:4610/healthz` shows the
  commit the dashboard serves), check it live, then merge the next.
- **At most one full test suite on the Mini at a time.** Sessions in this repo
  run on the Mini itself. They run only the test files they touch while they
  work, and one full run before their pull request; the updater's own run comes
  first. On 2026-10-15 parallel suites starved the updater's run and every
  deploy was held back for seven hours.
- **Never stop a process you did not start.** Stop only your own, by the PID
  you recorded or your own background task; never kill by name or pattern. The
  updater, the publisher and the dashboard run on the same machine.
- **Every visible change goes to Chris as a rendered before and after first**,
  small fixes included, at the sizes it affects, looked at by you before it is
  sent. Nothing merges without his OK on it.
- **One session talks to Chris.** When several sessions work, they send their
  files, questions and pull request links to the coordinating session, which
  checks them, shows him, and passes his words back verbatim.
- **Claude merges on Chris's yes**, pinned to the tested head commit
  (`gh pr merge <n> --squash --match-head-commit <sha>`), never red.
- **When the updater cannot land its own fix** (its limit is what the fix
  changes), one manual run of the updater's own code, with Chris's yes: its
  lock, its run record, its tests in a worktree, fast-forward only.
