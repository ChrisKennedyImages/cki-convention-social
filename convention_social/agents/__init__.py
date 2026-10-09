"""Agent registry: names, schedules and one-line jobs.

`schedule` is human-readable and mirrors the launchd plist that runs it;
`module` is imported by `bin/ccs run <agent>`; an agent whose module does not
exist yet reports "not built".
"""
from __future__ import annotations

AGENTS: dict[str, dict] = {
    "scanner":   {"schedule": "hourly",                "module": "convention_social.agents.scanner",
                  "job": "inventory the Drive photo library (read-only), then follow its changes; classify new photos"},
    "content":   {"schedule": "daily 06:00",           "module": "convention_social.agents.content",
                  "job": "pick tomorrow's photo from cleared photos, draft captions and designs into the review queue"},
    "publisher": {"schedule": "every 10 min",          "module": "convention_social.agents.publisher",
                  "job": "schedule approved posts through Buffer, verify they were sent"},
    "inbox":     {"schedule": "every 10 min",          "module": "convention_social.agents.inbox",
                  "job": "pull quote requests from eventcaliber.com, draft replies, send the ones Chris approved, publish booked dates"},
    "chief":     {"schedule": "daily at DIGEST_HOUR",  "module": "convention_social.agents.chief",
                  "job": "the morning brief: what needs Chris first, what the crew did, what it is watching"},
    "art_director": {"schedule": "inside each daily draft", "module": "convention_social.agents.art_director",
                  "job": "looks at every rendered post before Chris does: crop, legibility, composition; reworks or turns it back"},
    "watchdog":  {"schedule": "hourly; digest 07:30",  "module": "convention_social.agents.watchdog",
                  "job": "Drive sign-in, channels, failed posts, spend, missed runs; daily digest email"},
    "backup":    {"schedule": "nightly 02:30",         "module": "convention_social.agents.backup",
                  "job": "SQLite online backup to DATA_ROOT/backups (14 kept), a copy off the machine"},
    "dashboard": {"schedule": "always on (KeepAlive)", "module": "convention_social.dashboard.app",
                  "job": "review UI on 127.0.0.1:DASHBOARD_PORT"},
}


def is_built(name: str) -> bool:
    import importlib.util
    try:
        return importlib.util.find_spec(AGENTS[name]["module"]) is not None
    except ModuleNotFoundError:  # parent package not there yet
        return False
