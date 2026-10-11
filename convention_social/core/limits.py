"""Open file handles. macOS gives a launchd process 256 by default; the dashboard serving the Photos
tab (48 thumbnails at once, each a database connection, a Drive fetch and a file) ran out on
2026-10-11 ("OSError: [Errno 24] Too many open files"). Every process raises its own soft limit at
start, up to the hard limit the system allows; nothing machine wide is touched."""
from __future__ import annotations

OPEN_FILES_WANTED = 4096


def raise_open_files(wanted: int = OPEN_FILES_WANTED) -> int:
    """The soft limit after the call (unchanged where it cannot be raised)."""
    try:
        import resource
        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        target = wanted if hard == resource.RLIM_INFINITY else min(wanted, hard)
        if soft < target:
            resource.setrlimit(resource.RLIMIT_NOFILE, (target, hard))
            soft = target
        return soft
    except (ImportError, ValueError, OSError):
        return 0
