"""The tunnel: the dashboard away from home, through Cloudflare (Chris, 2026-10-15), never without Access in front.

A remotely-managed Cloudflare Tunnel: Chris creates it in Cloudflare's dashboard with one route, his address
(`TUNNEL_HOSTNAME`, dash.eventcaliber.com) to http://127.0.0.1:4610, and an Access application in front of that
address (docs/SETUP.md, 9a). The Mini keeps only its token (`CLOUDFLARE_TUNNEL_TOKEN`, in .env or the Keychain,
never in the repo, never shown). `cloudflared` reads it from its environment (TUNNEL_TOKEN), so it is in no file
and on no command line.

The launchd service (`launchd/com.chriskennedyimages.conventionsocial.tunnel.plist.template`) runs `ccs tunnel run`:

1. Every piece in place: the token, the address, the Access sign-in domain, the application's AUD tag, the one
   email. Else nothing starts.
2. From outside, every path of the address answers Cloudflare's sign-in, never the dashboard (access.check_outside).
   Else nothing starts.
3. cloudflared starts, and says which routes Cloudflare gave it: its info line "Updated to new configuration" with
   the routes' JSON in `config=` (orchestration/orchestrator.go in cloudflare/cloudflared, read 2026-10-15). Anything
   but the address to http://127.0.0.1:<DASHBOARD_PORT> and the closing http_status:404 (another port, another
   machine, another name) stops it at once; no routes said within CONFIRM_WITHIN stops it too. This suite's tunnel
   reaches this suite's dashboard and nothing else on the shared Mini. (Private network routes are kept apart from
   these by Cloudflare and are not in that line; SETUP adds none, and they serve only devices enrolled in Chris's
   own Zero Trust team.)

The dashboard itself refuses whatever came through Cloudflare without a valid Access token (access.refusal).
The Tailscale address is not touched. `scripts/install-daemons.sh` installs the service only when `ccs tunnel
check` passes; `scripts/go-live.sh` points the links at the address once the tunnel runs.
"""
from __future__ import annotations

import base64
import binascii
import json
import os
import queue
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urlsplit

from . import access, config, secrets

TOKEN_KEY = "CLOUDFLARE_TUNNEL_TOKEN"
LABEL = "com.chriskennedyimages.conventionsocial.tunnel"
CONFIRM_WITHIN = 120          # seconds for cloudflared to say which routes Cloudflare gave it
ROUTES_LINE = "Updated to new configuration"
STATUS_FILE = "tunnel.json"   # in the locks folder: what the service did last, for go-live and `ccs tunnel status`
CHILD_PATH = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
LABEL_RE = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
TOKEN_RE = re.compile(r"eyJ[A-Za-z0-9+/_=-]{20,}")


def _say(out, text: str) -> None:
    out.write(f"tunnel: {text}\n")
    out.flush()


# ---------------------------------------------------------------------------------------------- the details
def default_hostname() -> str:
    return f"dash.{config.get_config().brand_domain}"


def norm_hostname(raw: Optional[str]) -> str:
    """A name under the site's domain, never the domain itself or www (the Worker serves those: wrangler.jsonc);
    "" for anything else."""
    text = (raw or "").strip()
    host = (urlsplit(text if "//" in text else "//" + text).hostname or "").lower().strip(".")
    domain = (config.get_config().brand_domain or "").lower().strip(".")
    if not domain or not host.endswith("." + domain) or host == f"www.{domain}":
        return ""
    labels = host[:-len(domain) - 1].split(".")
    return host if all(re.fullmatch(LABEL_RE, part) for part in labels) else ""


def parse_token(raw: Optional[str]) -> str:
    """The tunnel's token (base64 JSON with the account, the tunnel and its secret), out of whatever was pasted:
    the token alone or Cloudflare's whole install command. "" when there is none."""
    for found in TOKEN_RE.findall(raw or ""):
        for decode in (base64.b64decode, base64.urlsafe_b64decode):
            try:
                data = json.loads(decode(found + "=" * (-len(found) % 4)))
            except (binascii.Error, ValueError, UnicodeDecodeError):
                continue
            if isinstance(data, dict) and all(isinstance(data.get(k), str) and data.get(k) for k in ("a", "t", "s")):
                return found
    return ""


def token() -> str:
    return parse_token(secrets.get_secret(TOKEN_KEY))


def command(binary: str) -> list[str]:
    """No origin and no token on the command line: Cloudflare holds the one route, the token is in the environment."""
    return [binary, "tunnel", "--no-autoupdate", "run"]


def child_env(tok: str) -> dict[str, str]:
    """Only what cloudflared needs. HOME is a folder of this suite's own, so it never reads a ~/.cloudflared that
    another program on the Mini may keep."""
    return {"HOME": str(config.get_config().data_root / "tunnel"), "PATH": CHILD_PATH, "TUNNEL_TOKEN": tok}


def find_cloudflared() -> Optional[str]:
    return shutil.which("cloudflared", path=CHILD_PATH)


# ---------------------------------------------------------------------------------------------- the routes
def route_problems(line: str, hostname: str, port: int) -> Optional[list[str]]:
    """None for a line that is not cloudflared saying which routes it was given; else what is wrong with them ([]:
    the address to our dashboard and the closing 404 only). A line this cannot read is a problem, never a pass."""
    if ROUTES_LINE not in line:
        return None
    raw = None
    text = line.strip()
    try:
        if text.startswith("{"):
            raw = json.loads(text).get("config")
        else:
            m = re.search(r'config=("(?:[^"\\]|\\.)*")', text)
            raw = json.loads(m.group(1)) if m else None
        cfg = json.loads(raw) if isinstance(raw, str) else None
    except (ValueError, AttributeError):
        cfg = None
    if not isinstance(cfg, dict):
        return ["cloudflared said it was given new routes, in a form this suite cannot read"]
    allowed = {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}
    ingress = cfg.get("ingress") if isinstance(cfg.get("ingress"), list) else []
    problems = [] if ingress else ["no routes at all"]
    for i, rule in enumerate(ingress):
        rule = rule if isinstance(rule, dict) else {}
        service = str(rule.get("service") or "").strip().rstrip("/")
        host = str(rule.get("hostname") or "").strip().lower()
        if i == len(ingress) - 1:
            if host or not service.startswith("http_status:"):
                problems.append(f"the last route is {service or 'empty'}{' for ' + host if host else ''}, "
                                "not the closing http_status:404")
            continue
        if host != hostname:
            problems.append(f"a route for {host or 'every name'} to {service or 'nothing'}")
        elif service not in allowed and not service.startswith("http_status:"):
            problems.append(f"{host} goes to {service or 'nothing'}, not http://127.0.0.1:{port}")
    if isinstance(cfg.get("warp-routing"), dict) and cfg["warp-routing"].get("enabled"):
        problems.append("private network routing is on")
    return problems


# ---------------------------------------------------------------------------------------------- status
def _status_path() -> Path:
    return config.get_config().locks_dir / STATUS_FILE


def write_status(state: str, why: str = "") -> None:
    path = _status_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"state": state, "why": why, "pid": os.getpid(), "at": int(time.time())}))


def read_status() -> dict:
    try:
        return json.loads(_status_path().read_text())
    except (OSError, ValueError):
        return {}


def _alive(pid) -> bool:
    try:
        os.kill(int(pid), 0)
    except (OSError, TypeError, ValueError):
        return False
    return True


# ---------------------------------------------------------------------------------------------- running
def supervise(cmd: list[str], env: dict, hostname: str, port: int, confirm_within: float = CONFIRM_WITHIN,
              out=None) -> int:
    """Run cloudflared, pass its lines to the log, and stop it the moment its routes are anything but ours,
    or when it has not said them within `confirm_within` seconds. Its exit code, or 4 (foreign route), 5 (no routes)."""
    out = out or sys.stderr
    write_status("starting")
    proc = subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    lines: queue.Queue = queue.Queue()

    def pump():
        for ln in proc.stdout:
            lines.put(ln)
        lines.put(None)
    threading.Thread(target=pump, daemon=True).start()

    def stop_child():
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()

    old = None
    if threading.current_thread() is threading.main_thread():
        def on_term(signum, frame):          # launchd stopping the service: cloudflared stops with it
            stop_child()
            write_status("stopped", "the service was stopped")
            raise SystemExit(0)
        old = signal.signal(signal.SIGTERM, on_term)
    try:
        confirmed, deadline = False, time.monotonic() + confirm_within
        while True:
            try:
                ln = lines.get(timeout=1.0 if confirmed else max(0.05, min(1.0, deadline - time.monotonic())))
            except queue.Empty:
                if not confirmed and time.monotonic() >= deadline:
                    why = f"cloudflared did not say which routes Cloudflare gave it within {int(confirm_within)} s"
                    _say(out, f"STOP {why}; stopped, so nothing runs unchecked")
                    write_status("refused", why)
                    stop_child()
                    return 5
                continue
            if ln is None:
                break
            out.write(ln)
            out.flush()
            problems = route_problems(ln, hostname, port)
            if problems is None:
                continue
            if problems:
                why = "; ".join(problems)
                _say(out, f"STOP Cloudflare routes this tunnel to more than this dashboard: {why}. cloudflared is "
                          f"stopped. In Cloudflare, Networking, Tunnels, this tunnel, keep one route: {hostname} to "
                          f"HTTP 127.0.0.1:{port}.")
                write_status("refused", why)
                stop_child()
                return 4
            if not confirmed:
                _say(out, f"the tunnel routes only to http://127.0.0.1:{port} (https://{hostname}); running")
                write_status("routed", f"https://{hostname} to http://127.0.0.1:{port}")
            confirmed = True
        code = proc.wait()
        write_status("stopped", f"cloudflared ended with {code}")
        return code
    finally:
        stop_child()
        if old is not None:
            signal.signal(signal.SIGTERM, old)


def _refuse(out, why: str, code: int) -> int:
    _say(out, f"not started: {why}")
    write_status("refused", why)
    return code


def run(out=None) -> int:
    """The launchd service. Starts cloudflared only when every gate passes (the module's docstring)."""
    out = out or sys.stderr
    s = access.settings()
    tok = token()
    missing = s.missing() + ([] if tok else [TOKEN_KEY])
    if missing:
        return _refuse(out, "missing on this Mini: " + ", ".join(missing) + " (docs/SETUP.md, 9a)", 2)
    binary = find_cloudflared()
    if not binary:
        return _refuse(out, "cloudflared is not installed (brew install cloudflared)", 2)
    ok, why = access.check_outside(s)
    if not ok:
        return _refuse(out, why, 3)
    _say(out, why)
    env = child_env(tok)
    Path(env["HOME"]).mkdir(parents=True, exist_ok=True)
    return supervise(command(binary), env, s.hostname, config.get_config().dashboard_port, out=out)


# ---------------------------------------------------------------------------------------------- for Chris
def others() -> list[str]:
    """cloudflared services on this Mini that are not this suite's: read, listed, left exactly as they are."""
    home = Path(os.path.expanduser("~"))
    found = []
    for folder in (Path("/Library/LaunchDaemons"), Path("/Library/LaunchAgents"), home / "Library" / "LaunchAgents"):
        try:
            names = sorted(p for p in folder.iterdir() if "cloudflare" in p.name.lower() and not p.name.startswith(LABEL))
        except OSError:
            continue
        found += [str(p) for p in names]
    return found


def check(out: Callable[[str], None] = print, get=None) -> bool:
    """`ccs tunnel check`: every piece, what else is on the Mini, and Access from outside. True only when ready."""
    s = access.settings()
    tok = token()
    ready = True

    def line(ok: bool, what: str, text: str):
        nonlocal ready
        ready = ready and ok
        out(f"  {'PASS' if ok else 'FAIL'}  {what:<14}{text}")
    line(bool(tok), "token", "set (never shown)" if tok else f"{TOKEN_KEY} is not set (bin/ccs tunnel setup)")
    line(bool(s.hostname), "address", f"https://{s.hostname}" if s.hostname else f"{access.HOST_KEY} is not set")
    line(bool(s.team and s.aud and s.email), "Access",
         f"sign-in at {s.team}, application tag set, only {s.email}" if s.team and s.aud and s.email
         else "missing: " + ", ".join(k for k in s.missing() if k != access.HOST_KEY))
    binary = find_cloudflared()
    line(bool(binary), "cloudflared", binary or "not installed: brew install cloudflared")
    theirs = others()
    out(f"  ----  {'on the Mini':<14}" + ("no other cloudflared service" if not theirs else
                                          "left as they are: " + ", ".join(theirs)))
    if not s.missing():
        ok, why = access.check_outside(s, get=get)
        line(ok, "from outside", why)
    else:
        line(False, "from outside", "not asked: the address and the Access details come first")
    out("READY: the tunnel can run" if ready else "NOT READY: nothing is started (the FAIL lines say why)")
    return ready


def status(wait: float = 0, use: bool = False, out: Callable[[str], None] = print) -> int:
    """`ccs tunnel status [--wait N] [--use]`: is the service running with only our route? With --use, the
    dashboard's links (DASHBOARD_PUBLIC_URL: pings, Approve, the site's own pings) move to the address."""
    deadline = time.time() + wait
    while True:
        st = read_status()
        if st.get("state") == "routed" and _alive(st.get("pid")):
            break
        if time.time() >= deadline:
            state = st.get("state") or "never run"
            out(f"the tunnel is not running ({state}{': ' + st['why'] if st.get('why') else ''})")
            return 1
        time.sleep(3)
    host = access.settings().hostname
    out(f"the tunnel runs: https://{host}, Cloudflare Access in front, routed only to this dashboard")
    if use and host:
        url = f"https://{host}"
        if config.get_config().dashboard_public_url != url:
            config.write_env({"DASHBOARD_PUBLIC_URL": url})
            out(f"pings and Approve links now open {url} (the Tailscale address still works when you open it)")
    return 0


def setup(ask: Callable[[str], str] = input, ask_secret: Optional[Callable[[str], str]] = None) -> int:
    """`ccs tunnel setup`: the details from Cloudflare (docs/SETUP.md, 9a), into .env. Nothing is shown back."""
    if ask_secret is None:
        import getpass
        ask_secret = getpass.getpass
    domain = config.get_config().brand_domain
    print("The dashboard away from home: the details from Cloudflare (docs/SETUP.md, 9a).")
    raw = ask(f"address [{default_hostname()}]: ").strip() or default_hostname()
    host = norm_hostname(raw)
    if not host:
        print(f"{raw} cannot be the dashboard's address: use a name under {domain} (not {domain} or www.{domain}, "
              "which are the site). Nothing saved.")
        return 2
    raw = ask("Access team domain (Zero Trust, Settings, Team name and domain: it ends in .cloudflareaccess.com): ")
    team = access.norm_team(raw)
    if not team:
        print(f"{raw.strip() or 'nothing'} is not a team domain on cloudflareaccess.com. Nothing saved.")
        return 2
    aud = access.norm_aud(ask("Application Audience (AUD) tag (the Access application, Additional settings): "))
    if not aud:
        print("that is not an Application Audience (AUD) tag: copy it whole from the Access application. Nothing saved.")
        return 2
    fallback = access.norm_email(config.getenv("ALERT_EMAIL"))
    raw = ask(f"the one email Access lets in{' [' + fallback + ']' if fallback else ''}: ").strip() or fallback
    email = access.norm_email(raw)
    if not email:
        print(f"{raw or 'nothing'} is not an email address. Nothing saved.")
        return 2
    tok = parse_token(ask_secret("the tunnel token (paste the whole install command Cloudflare shows; nothing is shown): "))
    if not tok:
        print("that holds no tunnel token (Cloudflare's starts with eyJ). Nothing saved.")
        return 2
    path = config.write_env({access.HOST_KEY: host, access.TEAM_KEY: team, access.AUD_KEY: aud,
                             access.EMAIL_KEY: email, TOKEN_KEY: tok})
    print(f"saved to {path} (the token is not shown). Do not run the install command Cloudflare showed: it would "
          "start the tunnel without this suite's Access check. scripts/go-live.sh installs the tunnel.")
    return 0
