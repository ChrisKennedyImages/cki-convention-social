"""The Mini's disk stays small (Chris, 2026-10-11: "The mini can't hold all these high res images or it
will kill the memory"). Only copies nothing needs are deleted, only inside the data folder; Drive keeps
every original and a preview is fetched again when it is next shown."""
from __future__ import annotations

import json
import os
import time

from convention_social import storage
from convention_social.agents import backup
from convention_social.core import config, db, runner
from tests._base import IsolatedCase

DAY = 86400


class Sweep(IsolatedCase):
    def setUp(self):
        super().setUp()
        self.conn = db.connect()
        self.addCleanup(self.conn.close)
        self.data = config.get_config().data_root
        self.now = time.time()
        now = db.utcnow()
        for i in (1, 2, 3):
            db.insert(self.conn, "photos", id=i, drive_id=f"d{i}", name=f"{i}.jpg", local_path=str(self.data / "photos" / f"d{i}.img"),
                      first_seen_at=now, last_seen_at=now)

    def file(self, rel, size=1000, age_days=0):
        p = self.data / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x" * size)
        t = self.now - age_days * DAY
        os.utime(p, (t, t))
        if p.parent.name.startswith(("2026-", "design-")):
            os.utime(p.parent, (t, t))
        return p

    def post(self, photo_ids, status, renders=None):
        now = db.utcnow()
        db.insert(self.conn, "content_queue", kind="photo", photo_ids=json.dumps(photo_ids), targets="[]", caption="{}",
                  status=status, render_paths=json.dumps(renders or {}), created_at=now, updated_at=now)

    def test_only_what_nothing_needs_goes_and_only_inside_the_data_folder(self):
        kept_open = self.file("photos/d1.img", age_days=30)            # on a draft
        gone = self.file("photos/d2.img", 5_000_000, age_days=30)      # its post went out
        fresh = self.file("photos/d3.img", age_days=1)                 # picked yesterday
        clean_gone = self.file("renders/clean/photo-2.jpg", age_days=30)
        old_day = self.file("renders/posts/2026-01-01/a.jpg", age_days=200)
        used_day = self.file("renders/posts/2026-01-02/b.jpg", age_days=200)
        sets = [self.file(f"renders/design-2026010{i}-1200/fan-post.jpg", age_days=10 - i) for i in range(1, 6)]
        untouched = [self.file(rel, age_days=400) for rel in ("music/track.mp3", "backups/convention_social-x.sqlite3",
                                                              "logs/dashboard.launchd.log", "renders/report-1/index.html")]
        self.post([1], "draft", {"4:5": [str(used_day)]})
        self.post([2], "published")
        result = storage.sweep(self.conn, now=self.now)
        for p in (kept_open, fresh, used_day, *sets[-3:], *untouched):
            self.assertTrue(p.exists(), p)
        for p in (gone, clean_gone, old_day, *sets[:2]):
            self.assertFalse(p.exists(), p)
        self.assertGreater(result["freed_mb"]["originals"], 4.7)
        self.assertIsNone(db.one(self.conn, "SELECT local_path FROM photos WHERE id=2")["local_path"])
        self.assertEqual(db.one(self.conn, "SELECT local_path FROM photos WHERE id=1")["local_path"], str(kept_open))
        self.assertIn("GB free", storage.summary(result))

    def test_previews_are_trimmed_oldest_first_past_the_cap(self):
        thumbs = [self.file(f"thumbs/t{i}.jpg", 400_000, age_days=10 - i) for i in range(10)]   # 4 MB
        storage.sweep(self.conn, now=self.now, thumbs_cap_mb=3)
        left = [p for p in thumbs if p.exists()]
        self.assertEqual(left, thumbs[-len(left):], "the newest previews stay")
        self.assertLessEqual(sum(p.stat().st_size for p in left), 3 * 1024 * 1024 * 0.8)
        self.assertGreater(len(left), 0)

    def test_the_nightly_backup_runs_the_sweep_and_says_what_it_freed(self):
        self.file("photos/d2.img", age_days=30)
        self.post([2], "rejected")
        ctx = runner.Context("backup", self.conn, __import__("logging").getLogger("t"), config.get_config(), False, 0)
        line = backup.run(ctx, put=lambda *a, **k: None)
        self.assertIn("disk: freed", line)
        self.assertFalse((self.data / "photos" / "d2.img").exists())
