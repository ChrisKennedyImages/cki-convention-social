#!/usr/bin/env python3
"""The whole suite in several processes at once (bin/test with no arguments runs this).

Chris, 2026-11-09: a fix that takes minutes to write waited on a suite that ran in one process on one of the Mini's
ten cores. Every test already works in a data root of its own (tests/_base.py), so the files can run side by side: each
process gets a throwaway HOME, data root and env file of its own, exactly as bin/test gave the one process.

Measured on the Mini that night, alone: one process 8 min 57 s. A process per file or per class was slower than a few
long-lived ones (7 to 9 min): what a process works out once (fonts, textures, the site's logos) every new process works
out again. So the files are dealt into a few shares of about the same weight, each share one process. A file's weight is
the time it took on the last passing run on this machine (kept in ~/.cache/ccs-test-times.json, outside the repo), its
size where there is none yet.

Fail closed: any failure, error or skip, a file that ran no test, or a file that was not run, fails the run. Prints the
same last lines unittest does, the failing tests by name, and where each share's whole output is kept.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SECRETS = ("ANTHROPIC_API_KEY", "BUFFER_API_KEY", "SMTP_PASSWORD", "R2_KEY", "R2_SECRET", "MEDIA_UPLOAD_TOKEN",
           "GOOGLE_OAUTH_CLIENT_SECRET", "CLOUDFLARE_TUNNEL_TOKEN", "GITHUB_TOKEN")
TIMES = Path.home() / ".cache" / "ccs-test-times.json"
SKIPPED = re.compile(r"skipped=([1-9]\d*)")
NAMED = re.compile(r"^(?:FAIL|ERROR): .+$", re.M)
FILED = re.compile(r"^FILED (\S+) (\d+) ([\d.]+) (\d)$", re.M)
# one share: its files one after another in this process, each timed; exit 1 if any did not pass
SHARE = """
import sys, time, unittest
bad = False
for name in sys.argv[1:]:
    began = time.time()
    result = unittest.TextTestRunner(stream=sys.stdout).run(unittest.defaultTestLoader.loadTestsFromName(name))
    bad = bad or not result.wasSuccessful()
    print(f"FILED {name} {result.testsRun} {time.time() - began:.2f} {int(result.wasSuccessful())}", flush=True)
sys.exit(1 if bad else 0)
"""


def workers() -> int:
    asked = os.environ.get("CCS_TEST_WORKERS", "")
    if asked.isdigit() and int(asked) > 0:
        return int(asked)
    return max(1, min(8, (os.cpu_count() or 2) - 2))


def weights(files: list[Path]) -> dict[Path, float]:
    """Each file's weight: its seconds on the last passing run here; else its size, scaled to the known ones."""
    try:
        known = json.loads(TIMES.read_text())
    except (OSError, ValueError):
        known = {}
    timed = {f: float(known[f.stem]) for f in files if isinstance(known.get(f.stem), (int, float))}
    per_byte = (sum(timed.values()) / max(1, sum(f.stat().st_size for f in timed))) if timed else 1.0
    return {f: timed.get(f, f.stat().st_size * per_byte) for f in files}


def shares(files: list[Path], n: int) -> list[list[Path]]:
    """The files in `n` shares of about the same weight, the heaviest placed first."""
    weight = weights(files)
    out: list[tuple[float, list[Path]]] = [(0.0, []) for _ in range(n)]
    for f in sorted(files, key=lambda f: -weight[f]):
        k = min(range(n), key=lambda i: out[i][0])
        out[k] = (out[k][0] + weight[f], out[k][1] + [f])
    return [share for _, share in out if share]


def run_share(python: str, k: int, files: list[Path], logs: Path) -> dict:
    home = Path(tempfile.mkdtemp(prefix=f"ccs-test-{k}-"))
    env = {key: v for key, v in os.environ.items() if key not in SECRETS}
    env.update(HOME=str(home), CCS_DATA_ROOT=str(home / "data"), CCS_ENV_FILE=str(home / "nonexistent.env"))
    began = time.time()
    r = subprocess.run([python, "-B", "-c", SHARE, *[f"tests.{f.stem}" for f in files]], cwd=str(ROOT), env=env,
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    out = r.stdout or ""
    log = logs / f"share-{k}.log"
    log.write_text(out)
    return {"k": k, "code": r.returncode, "took": time.time() - began, "log": log,
            "filed": {m[0].split(".", 1)[1]: (int(m[1]), float(m[2]), m[3] == "1") for m in FILED.findall(out)},
            "skips": sum(int(n) for n in SKIPPED.findall(out)), "named": NAMED.findall(out)}


def main() -> int:
    venv = ROOT / ".venv" / "bin" / "python"
    python = str(venv) if venv.exists() else sys.executable
    files = sorted((ROOT / "tests").glob("test_*.py"))
    if not files:
        print("no test files found: nothing was run")
        return 1
    parts = shares(files, workers())
    logs = Path(tempfile.mkdtemp(prefix="ccs-test-logs-"))
    began = time.time()
    with ThreadPoolExecutor(len(parts)) as pool:
        results = list(pool.map(lambda kp: run_share(python, kp[0], kp[1], logs), enumerate(parts)))
    took = time.time() - began
    filed = {name: got for r in results for name, got in r["filed"].items()}
    total = sum(ran for ran, _, _ in filed.values())
    named = [line for r in results for line in r["named"]]
    skips = sum(r["skips"] for r in results)
    not_run = [f.stem for f in files if f.stem not in filed]
    empty = [name for name, (ran, _, _) in filed.items() if ran == 0]
    bad = [r for r in results if r["code"] != 0]
    print("-" * 70)
    print(f"Ran {total} tests in {took:.3f}s ({len(files)} files in {len(parts)} processes)")
    print()
    ok = not bad and not skips and not not_run and not empty and total > 0
    print("OK" if ok else f"FAILED (processes failed={len(bad)}, named={len(named)}, skipped={skips})")
    if named:
        print("Failing:")
        print("\n".join(named))
    if not_run:
        print("not run: " + ", ".join(not_run))
    if empty:
        print("ran no test: " + ", ".join(empty))
    if skips:
        print("SKIPS ARE FAILURES")
    if not ok:
        print(f"Full output: {logs}")
    else:
        try:        # the next run deals the files by what they took now
            TIMES.parent.mkdir(parents=True, exist_ok=True)
            TIMES.write_text(json.dumps({name: secs for name, (_, secs, _) in sorted(filed.items())}, indent=0))
        except OSError:
            pass
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
