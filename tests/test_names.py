"""No public word says which event or who is in the photo. Chris, 2026-10-11: "Because A LOT of the
images are ACU and CPAC (the same company) i want to make sure the captions don't say the specific
event or person." Pinned at every writer and at both gates: Approve on the dashboard and the
publisher's last check before anything leaves."""
from __future__ import annotations

import json
import os
import types
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from convention_social.agents import content, publisher
from convention_social.ai import claude, copy_rules, names
from convention_social.core import auth, config, db, runner
from convention_social.dashboard.app import COOKIE, create_app, make_token
from convention_social.render import meta
from convention_social.site import build
from tests._base import IsolatedCase
from tests._fakes import AgentCase, add_channels, add_photo, add_post, all_eligible, make_ctx, write_render
from tests._photos import jpeg_bytes


def library(conn):
    now = db.utcnow()
    db.insert(conn, "drive_folders", drive_id="fe", name="Conference 2025", clearance="cleared", first_seen_at=now, last_seen_at=now)
    pid = db.insert(conn, "photos", drive_id="e1", name="e1.jpg", folder_id="fe", width=3000, height=2000,
                    taken_at="2025:02:14 10:00:00", first_seen_at=now, last_seen_at=now)
    db.insert(conn, "classifications", photo_id=pid, method="ollama", subject="event", convention_name="Liberty Summit 2025",
              event_kind="business", is_convention=1, quality=5, possible_minor=0, personal_details="[]", space="exterior",
              residential=0, empty_room=0, sharp=1, light=4, moment=4, shot_type="stage_panel",
              summary="A speaker at the CPAC podium, Jordan Example, in front of an ACU banner.", classified_at=now)
    db.insert(conn, "credits", scope="photo", drive_id="e1", person_name="Jordan Example", handle="@jordan.ex", consent="yes",
              synced_at=now)
    return pid


class Gate(IsolatedCase):
    def test_every_name_the_suite_knows_and_the_two_chris_named(self):
        conn = db.connect()
        library(conn)
        db.insert(conn, "conventions", name="Katsucon 2026", created_at=db.utcnow(), updated_at=db.utcnow())
        db.insert(conn, "classifications", photo_id=db.insert(conn, "photos", drive_id="x", name="x", first_seen_at=db.utcnow(),
                                                               last_seen_at=db.utcnow()),
                  method="folder", convention_name="unknown", classified_at=db.utcnow())
        known = names.public_names(conn)
        conn.close()
        for n in ("CPAC", "ACU", "American Conservative Union", "Liberty Summit", "Liberty Summit 2025", "Katsucon",
                  "Jordan Example", "jordan.ex"):
            self.assertIn(n, known)
        self.assertNotIn("unknown", known, "a placeholder is not a name")

    def test_names_are_found_however_they_are_written(self):
        known = ["Conservative Political Action Conference", "Liberty Summit", "CPAC", "ACU", "Jordan Example"]
        for text in ("Backstage at CPAC.", "#CPAC2025", "#cpacphotos", "the cpac stage", "ACU staff", "On stage at the Liberty Summit",
                     "Thanks @jordan.ex", "Jordan Example on stage", "#LibertySummit"):
            with self.subTest(text):
                self.assertFalse(copy_rules.check(text, names=known).ok)
                self.assertEqual(copy_rules.check(text, names=known).blocks[0].rule, "names")
        for text in ("A political conference, backstage before the keynote.", "A vacuum of light on stage.",
                     "Request a quote at hello@eventcaliber.com", "Accurate color, every room."):
            with self.subTest(text):
                self.assertTrue(copy_rules.check(text, names=known).ok)
        self.assertTrue(copy_rules.check("Backstage at CPAC.").ok, "private mail (no names passed) is not covered")


class Writers(IsolatedCase):
    def test_the_caption_writer_is_never_told_which_event_or_who(self):
        conn = db.connect()
        seen = {}

        class Client:
            beta = messages = None

            def create(self, **kw):
                seen.update(kw)
                body = {"photo_summary": "A speaker.",
                        "captions": {n: "A conference stage before the keynote." for n in claude.NETWORKS}}
                return types.SimpleNamespace(content=[types.SimpleNamespace(type="text", text=json.dumps(body))], stop_reason="end_turn",
                                             model="claude-opus-5", usage=types.SimpleNamespace(input_tokens=10, output_tokens=10))
        client = Client()
        client.beta = client.messages = client
        photo = self.root / "p.jpg"
        photo.write_bytes(jpeg_bytes())
        os.environ["AI_MONTHLY_CAP_USD"] = "5"
        config.reset()
        claude.ClaudeDrafter(conn, client=client).draft(claude.PostFacts(brand_name="Event Caliber", event_kind="business"), photo)
        text = seen["messages"][0]["content"][1]["text"]
        self.assertIn("a conference (never name which event, or anyone in the photo)", text)
        self.assertNotIn("Credit", text)
        self.assertIn("Never name the event", seen["system"][0]["text"])
        self.assertIn("never tag anyone with an @handle", seen["system"][0]["text"])
        self.assertFalse(hasattr(claude.PostFacts("x"), "event_name"), "there is no field to pass a name through")
        conn.close()

    def test_the_template_says_the_kind_of_event_only(self):
        for kind, want in (("business", "A moment from a conference."), ("fan", "A moment from a convention."),
                           ("unknown", "A moment from an event.")):
            d = claude.TemplateDrafter().draft(claude.PostFacts(brand_name="Event Caliber", event_kind=kind), Path("unused"))
            self.assertTrue(d.captions["facebook"].startswith(want))

    def test_the_line_printed_on_the_post_names_no_event(self):
        self.assertEqual(content.kicker_for({"subject": "event", "event_kind": "business", "convention_name": "CPAC 2025"}), "Conference photography")
        self.assertEqual(content.kicker_for({"subject": "event", "event_kind": "fan", "convention_name": "Katsucon"}), "Convention photography")
        self.assertEqual(content.kicker_for({"subject": "event", "event_kind": None}), "Event photography")
        self.assertEqual(content.kicker_for({"subject": "architecture", "event_kind": None}), "Venue photography")
        for row in ({"subject": "event", "event_kind": k} for k in ("business", "fan", None)):
            self.assertIn("photography", content.kicker_for(row), "Chris, 2026-10-11: it should say photography somewhere")

    def test_the_search_fields_in_the_image_file_name_no_one(self):
        conn = db.connect()
        pid = library(conn)
        row = dict(db.one(conn, "SELECT p.*, c.* FROM photos p JOIN classifications c ON c.photo_id=p.id WHERE p.id=?", (pid,)))
        row["credit"] = "@jordan.ex"
        m = meta.for_photo(conn, row)
        self.assertEqual(m.title, "Stage panel at a conference")
        everything = " ".join([m.title, m.description, *m.keywords, m.credit]).lower()
        for name in ("cpac", "acu", "liberty", "jordan"):
            self.assertNotIn(name, everything)
        db.insert(conn, "photo_seo", photo_id=pid, slug="s", title="Speaker at CPAC", alt="Speaker at CPAC", description="d",
                  keywords="[]", model="template", written_at=db.utcnow())
        self.assertEqual(meta.for_photo(conn, row).title, "Stage panel at a conference", "old text that names CPAC is not used")
        conn.close()

    def test_the_website_alt_text_is_never_the_sorters_description(self):
        row = {"subject": "event", "shot_type": "stage_panel", "summary": "A speaker at the CPAC podium, Jordan Example."}
        self.assertEqual(build.site_alt(row), "Stage panel")
        self.assertEqual(build.site_alt({"subject": "architecture"}), "Venue and architecture photography")


class Gates(AgentCase):
    def setUp(self):
        super().setUp()
        self.conn = self.connect()
        add_channels(self.conn, "instagram", "facebook", "pinterest")
        os.environ["PINTEREST_BOARD_ID"] = "board-123"
        config.reset()

    def named_post(self, status):
        pid = add_photo(self.conn, self.root / "photos")
        caps = {"instagram": "Backstage before the keynote. #CPAC2025", "facebook": "Backstage before the keynote.",
                "pinterest": "Backstage before the keynote."}
        return add_post(self.conn, [pid], captions=caps, status=status,
                        render_paths={"4:5": [write_render(self.root / "data" / "r", "a.jpg")]})

    def test_a_caption_that_names_the_event_is_rewritten_before_he_sees_it(self):
        # Chris, 2026-10-12: "the captions should auto correct themselves ... I don't want to change any captions"
        os.environ["DASHBOARD_PASSWORD_HASH"] = auth.hash_password("correct horse")
        config.reset()
        qid = self.named_post("draft")
        client = TestClient(create_app())
        client.cookies.set(COOKIE, make_token("chris"))
        page = client.get(f"/queue/{qid}").text
        self.assertIn("the suite rewrote it. Nothing to fix.", page)
        self.assertIn("names &#39;CPAC&#39;", page, "the note says what was wrong")
        self.assertNotIn('class="rule block"', page)
        captions = json.loads(db.one(self.conn, "SELECT caption FROM content_queue WHERE id=?", (qid,))["caption"])
        for text in captions.values():
            self.assertNotIn("CPAC", text)
            self.assertTrue(copy_rules.check(text, names=names.public_names(self.conn), social=True).ok, text)
        r = client.post(f"/queue/{qid}/approve", follow_redirects=False)
        self.assertNotIn("msg=blocked", r.headers["location"])
        self.assertIn("msg=ineligible", r.headers["location"], "the photo gate still holds; the name never does the blocking")
        self.assertEqual(db.one(self.conn, "SELECT status FROM content_queue WHERE id=?", (qid,))["status"], "draft")

    def test_the_publisher_rewrites_a_post_that_names_the_event_before_it_goes(self):
        """The door used to send it back to Chris; since 2026-10-13 it rewrites first and checks again."""
        qid = self.named_post("approved")
        with mock.patch.object(publisher, "_eligibility_module", return_value=all_eligible()):
            stats = publisher.publish_ready(make_ctx(self.conn), now=datetime(2026, 10, 12, 12, tzinfo=timezone.utc))
        self.assertEqual((stats["turned_back"], stats["would_publish"]), (0, 1))
        row = db.one(self.conn, "SELECT status, caption, payload, rule_report FROM content_queue WHERE id=?", (qid,))
        self.assertEqual(row["status"], "would_publish")
        for text in (row["caption"], row["payload"]):
            self.assertNotIn("CPAC", text)
            self.assertNotIn("Jordan", text)
        self.assertIn("CPAC", json.dumps(json.loads(row["rule_report"])["mended"][-1]["fixed"]), "the record names the rule")


class DailyDraft(IsolatedCase):
    def test_a_conference_photo_is_drafted_with_no_name_anywhere_public(self):
        conn = db.connect()
        library(conn)
        config.get_config().ensure_dirs()
        ctx = runner.Context("content", conn, __import__("logging").getLogger("t"), config.get_config(), True, 0)
        line = content.draft_one(ctx, lambda row: jpeg_bytes(seed=1, size=(3000, 2000)),
                                 now=datetime(2026, 10, 13, 10, tzinfo=timezone.utc))          # tomorrow: Wednesday, a single
        self.assertIn("drafted post", line)
        row = db.one(conn, "SELECT caption, render_paths, rule_report FROM content_queue")
        report = json.loads(row["rule_report"])
        self.assertTrue(all(r["ok"] for r in report["rules"].values()), report["rules"])
        text = row["caption"].lower()
        for name in ("cpac", "acu", "liberty", "jordan"):
            self.assertNotIn(name, text)
        for paths in json.loads(row["render_paths"]).values():
            fields = meta.search_text(Path(paths[0])).lower()           # the EXIF, XMP and IPTC text, never the pixels
            self.assertIn("event caliber", fields, "the reader sees the file's own fields")
            self.assertIn("stage panel", fields)
            for name in ("cpac", "liberty", "jordan"):
                self.assertNotIn(name, fields, "nor in the file's own search fields")
        conn.close()


class NothingUnread(IsolatedCase):
    def test_the_caption_writer_asks_for_nothing_it_never_reads(self):
        """2026-10-24 audit: Draft.privacy was asked of the model on every caption and read by nothing."""
        self.assertNotIn("privacy", claude.SYSTEM_PROMPT)
        self.assertNotIn("privacy", claude.OUTPUT_SCHEMA["properties"])
        self.assertFalse(hasattr(claude.Draft, "privacy"))
