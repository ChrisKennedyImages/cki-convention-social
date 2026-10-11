"""SEO: the site markup, photo search text (template and Claude, every answer checked), the weekly
read-only site check, and the dashboard page. No network: Claude and the site are fakes."""
from __future__ import annotations

import json
import os
import types
import xml.etree.ElementTree as ET
from pathlib import Path

from fastapi.testclient import TestClient

from convention_social import seo
from convention_social.agents import seo as seo_agent
from convention_social.ai import copy_rules
from convention_social.core import auth, config, db, runner
from convention_social.seo import markup, photo_text, site_check
from convention_social.site import build
from tests._fakes import AgentCase, make_ctx
from tests.test_banned_words import BANNED

BASE = "https://eventcaliber.com"
NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
IMG = "{http://www.google.com/schemas/sitemap-image/1.1}"
GOOD = {"title": "Cosplay portrait at Katsucon 2025",
        "alt": "Cosplayer in a red cape posing by a tall window at Katsucon 2025",
        "description": "A cosplay portrait at Katsucon 2025. Event and convention photography by Event Caliber.",
        "keywords": ["event photography", "cosplay portrait", "katsucon 2025", "anime convention photography"]}


class Recorder:
    def __init__(self, owner, path):
        self.owner, self.path = owner, path

    def create(self, **kw):
        self.owner.calls.append((self.path, kw))
        if self.owner.error:
            raise self.owner.error
        answer = self.owner.answer(len(self.owner.calls)) if callable(self.owner.answer) else self.owner.answer
        block = types.SimpleNamespace(type="text", text=json.dumps(answer))
        return types.SimpleNamespace(content=[block], stop_reason=self.owner.stop, model=kw["model"],
                                     usage=types.SimpleNamespace(input_tokens=400, output_tokens=120))


class FakeClaude:
    """messages.create and beta.messages.create, recorded separately."""

    def __init__(self, answer=None, stop="end_turn", error=None):
        self.calls = []
        self.answer = answer if answer is not None else dict(GOOD)
        self.stop = stop
        self.error = error
        self.messages = Recorder(self, "plain")
        self.beta = types.SimpleNamespace(messages=Recorder(self, "beta"))


class SeoCase(AgentCase):
    def setUp(self):
        super().setUp()
        self.conn = self.connect()
        self.n = 0

    def ctx(self, dry_run=False):
        return make_ctx(self.conn, agent="seo", dry_run=dry_run)

    def photo(self, *, subject="event", shot="cosplay_portrait", event="Katsucon", kind="fan", taken="2025-02-15T12:00:00",
              view=None, summary="A cosplayer in a red cape poses by a tall window.", final=True, folder="fcon"):
        self.n += 1
        now = db.utcnow()
        if not db.one(self.conn, "SELECT 1 FROM drive_folders WHERE drive_id=?", (folder,)):
            db.insert(self.conn, "drive_folders", drive_id=folder, name=folder, clearance="cleared", first_seen_at=now, last_seen_at=now)
        pid = db.insert(self.conn, "photos", drive_id=f"drive-{self.n}", name=f"p{self.n}.jpg", folder_id=folder, taken_at=taken,
                        first_seen_at=now, last_seen_at=now)
        db.insert(self.conn, "classifications", photo_id=pid, method="vision", subject=subject, shot_type=shot, convention_name=event,
                  event_kind=kind, view=view, possible_minor=0, personal_details="[]", summary=summary,
                  space="exterior", residential=0, empty_room=0, sharp=1, light=4, moment=4, classified_at=now)
        if final:
            db.insert(self.conn, "final_checks", photo_id=pid, possible_minor=0, personal_details="[]", model="claude-opus-5",
                      checked_at=now)
        return pid

    def credit(self, pid, handle=None, name=None):
        drive_id = db.one(self.conn, "SELECT drive_id FROM photos WHERE id=?", (pid,))["drive_id"]
        db.insert(self.conn, "credits", scope="photo", drive_id=drive_id, person_name=name, handle=handle, consent="yes",
                  synced_at=db.utcnow())

    def calendar(self, folder="fcon", name="Katsucon", city="National Harbor"):
        now = db.utcnow()
        cid = db.insert(self.conn, "conventions", name=name, kind="fan", city=city, start_date="2025-02-14", created_at=now, updated_at=now)
        self.conn.execute("UPDATE drive_folders SET convention_id=? WHERE drive_id=?", (cid, folder))
        return cid

    def queue(self, *photo_ids, status="draft"):
        now = db.utcnow()
        return db.insert(self.conn, "content_queue", kind="photo", photo_ids=json.dumps(list(photo_ids)), targets='["instagram"]',
                         caption='{"instagram": "x"}', status=status, created_at=now, updated_at=now)

    def row(self, pid):
        return db.one(self.conn, "SELECT * FROM photo_seo WHERE photo_id=?", (pid,))

    def spent(self):
        return db.one(self.conn, "SELECT COUNT(*) n FROM api_usage WHERE provider='anthropic'")["n"]

    def assert_public(self, row):
        self.assertIsNotNone(row)
        for k in ("title", "alt", "description"):
            self.assertTrue(row[k], k)
            self.assertTrue(copy_rules.check(row[k]).ok, (k, row[k]))
        self.assertLess(len(row["alt"]), 125)
        kws = json.loads(row["keywords"])
        self.assertTrue(5 <= len(kws) <= 10, kws)


# ------------------------------------------------------------------ markup

class Markup(SeoCase):
    def test_sitemap_lists_pages_and_images(self):
        xml = seo.sitemap_xml(BASE, ["/", "/book/", "/"], {
            "/": [{"loc": "/assets/hero-1600.jpg", "title": "Cosplay portrait & friends", "caption": "Katsucon 2025 hall"}],
            "/work/": [{"loc": "https://eventcaliber.com/assets/w.jpg"}]})
        self.assertTrue(xml.startswith('<?xml version="1.0" encoding="UTF-8"?>'))
        root = ET.fromstring(xml.encode())
        self.assertEqual(root.tag, f"{NS}urlset")
        locs = [u.find(f"{NS}loc").text for u in root.findall(f"{NS}url")]
        self.assertEqual(locs, [f"{BASE}/", f"{BASE}/book/", f"{BASE}/work/"])
        images = root.findall(f"{NS}url/{IMG}image")
        self.assertEqual(len(images), 2)
        self.assertEqual(images[0].find(f"{IMG}loc").text, f"{BASE}/assets/hero-1600.jpg")
        self.assertEqual(images[0].find(f"{IMG}title").text, "Cosplay portrait & friends")
        self.assertEqual(images[0].find(f"{IMG}caption").text, "Katsucon 2025 hall")
        self.assertIsNone(images[1].find(f"{IMG}title"))

    def test_sitemap_refuses_copy_that_breaks_a_rule(self):
        with self.assertRaises(seo.SeoCopyRefused):
            seo.sitemap_xml(BASE, ["/"], {"/": [{"loc": "/a.jpg", "caption": "Portraits from $99"}]})
        with self.assertRaises(seo.SeoCopyRefused):
            seo.sitemap_xml(BASE, ["/"], {"/": [{"loc": "/a.jpg", "title": "Official photographer of the con"}]})

    def test_robots(self):
        text = seo.robots_txt(BASE + "/")
        self.assertIn("Sitemap: https://eventcaliber.com/sitemap.xml", text)
        self.assertIn("Disallow: /api/", text)
        self.assertNotIn("Disallow: /\n", text)
        self.assertTrue(site_check.check_robots(200, text)["ok"])

    def test_business_block_has_no_address_and_a_phone_only_when_given(self):
        data = seo.jsonld_business("Event Caliber", "CKI, LLC", BASE, "hello@eventcaliber.com", "Event and convention photography.")
        self.assertEqual(data["@type"], "ProfessionalService")
        self.assertEqual(data["sameAs"], [])
        self.assertEqual(sorted(data), ["@context", "@type", "description", "email", "legalName", "name", "sameAs", "url"])
        self.assertNotIn("address", json.dumps(data).lower())
        with_phone = seo.jsonld_business("Event Caliber", "CKI, LLC", BASE, "h@e.com", "Event photography.", telephone=" 555 0100 ")
        self.assertEqual(with_phone["telephone"], "555 0100")
        for bad in ("Coverage from $500 a day.", "The official photographer for big cons.", "Trusted by every expo."):
            with self.assertRaises(seo.SeoCopyRefused):
                seo.jsonld_business("Event Caliber", "CKI, LLC", BASE, "h@e.com", bad)

    def test_image_block_carries_only_the_five_fields(self):
        data = seo.jsonld_image(f"{BASE}/assets/a.jpg", "Event Caliber", "CKI, LLC", "Event Caliber, @kat.cos")
        self.assertEqual(sorted(data), ["@context", "@type", "contentUrl", "copyrightHolder", "copyrightNotice", "creator", "creditText"])
        self.assertEqual(data["@type"], "ImageObject")
        self.assertEqual(data["creator"], {"@type": "Organization", "name": "Event Caliber"})
        self.assertEqual(data["copyrightHolder"], {"@type": "Organization", "name": "CKI, LLC"})
        self.assertEqual(data["copyrightNotice"], "© CKI, LLC")
        self.assertEqual(data["creditText"], "Event Caliber, @kat.cos")
        text = json.dumps(data).lower()
        self.assertTrue(BANNED)
        self.assertEqual([w for w in BANNED if w in text], [])
        with self.assertRaises(seo.SeoCopyRefused):
            seo.jsonld_image(f"{BASE}/a.jpg", "Event Caliber", "CKI, LLC", "Prints from $20")

    def test_script_tag_cannot_close_early(self):
        tag = seo.jsonld_script({"name": "</script><b>"})
        self.assertTrue(tag.startswith('<script type="application/ld+json">'))
        self.assertEqual(tag.count("</script>"), 1)


# ------------------------------------------------------------------ the template

class Template(SeoCase):
    def test_event_photo(self):
        pid = self.photo()
        self.credit(pid, handle="@kat.cos")
        self.credit(pid, name="Jordan Example")
        self.calendar()
        stats = photo_text.write_all(self.conn, dry_run=True)
        self.assertEqual(stats["written"], 1)
        r = self.row(pid)
        self.assert_public(r)
        self.assertEqual(r["model"], "template")
        self.assertEqual(r["slug"], "cosplay-portrait-katsucon-2025")
        self.assertEqual(r["title"], "Cosplay portrait at Katsucon 2025")
        self.assertEqual(r["alt"], "Cosplay portrait of @kat.cos at Katsucon 2025")
        self.assertNotIn("Jordan", r["alt"] + r["title"] + r["description"])
        kws = json.loads(r["keywords"])
        for k in ("event photography", "convention photography", "fan convention photography", "cosplay portrait",
                  "national harbor event photography"):
            self.assertIn(k, kws)

    def test_the_city_comes_only_from_the_calendar(self):
        pid = self.photo(summary="A cosplayer outside the Gaylord in National Harbor.")
        photo_text.write_all(self.conn, dry_run=True)
        r = self.row(pid)
        self.assertIsNotNone(r)
        self.assertNotIn("national harbor", (r["keywords"] + r["alt"] + r["description"] + r["title"]).lower())

    def test_building_is_described_by_type_never_by_name_or_number(self):
        pid = self.photo(subject="architecture", shot="building_exterior", event="Smith Tower 1200", kind="unknown",
                         view="exterior", summary="The Smith Tower at 1200 Main Street at dusk.", folder="farch")
        photo_text.write_all(self.conn, dry_run=True)
        r = self.row(pid)
        self.assert_public(r)
        text = r["title"] + r["alt"] + r["description"] + r["keywords"] + r["slug"]
        self.assertNotIn("smith", text.lower())
        self.assertNotIn("1200", text)
        self.assertEqual(r["alt"], "Exterior view of a building")
        self.assertIn("architecture photography", json.loads(r["keywords"]))

    def test_slugs_are_unique_and_never_change(self):
        a, b = self.photo(), self.photo()
        photo_text.write_all(self.conn, dry_run=True)
        self.assertEqual(self.row(a)["slug"], "cosplay-portrait-katsucon-2025")
        self.assertEqual(self.row(b)["slug"], f"cosplay-portrait-katsucon-2025-{b}")
        photo_text.write_all(self.conn, dry_run=False, client=FakeClaude())
        self.assertEqual(self.row(a)["model"], "claude-haiku-4-5")
        self.assertEqual(self.row(a)["slug"], "cosplay-portrait-katsucon-2025")

    def test_slugify(self):
        self.assertEqual(photo_text.slugify("Cosplay Portrait: Katsucon 2025!"), "cosplay-portrait-katsucon-2025")
        self.assertEqual(photo_text.slugify("Café Con — Day 2"), "cafe-con-day-2")
        long = photo_text.slugify("word " * 40)
        self.assertTrue(long)
        self.assertLessEqual(len(long), 70)
        self.assertFalse(long.endswith("-"))

    def test_which_photos_get_text(self):
        postable = self.photo()
        unchecked = self.photo(final=False)                 # never given the final check, not queued
        queued = self.photo(final=False)                    # a candidate on a draft
        listed = self.photo(final=False)                    # queued, then put on the do-not-use list
        self.queue(queued)
        self.queue(listed)
        db.insert(self.conn, "do_not_use", kind="photo", value=f"drive-{listed}", added_at=db.utcnow())
        stats = photo_text.write_all(self.conn, dry_run=True)
        self.assertEqual(stats["written"], 2)
        self.assertEqual(stats["left_out"], 1)
        self.assertIsNotNone(self.row(postable))
        self.assertIsNotNone(self.row(queued))
        self.assertIsNone(self.row(unchecked))
        self.assertIsNone(self.row(listed))


# ------------------------------------------------------------------ Claude

class Writer(SeoCase):
    def test_haiku_writes_it_and_the_spend_is_recorded(self):
        pid = self.photo()
        fake = FakeClaude()
        stats = photo_text.write_all(self.conn, dry_run=False, client=fake)
        self.assertEqual(stats["claude"], 1)
        r = self.row(pid)
        self.assert_public(r)
        self.assertEqual(r["model"], "claude-haiku-4-5")
        self.assertEqual(r["alt"], GOOD["alt"])
        self.assertEqual(len(fake.calls), 1)
        path, kw = fake.calls[0]
        self.assertEqual(path, "plain")
        self.assertEqual(kw["model"], "claude-haiku-4-5")
        self.assertNotIn("thinking", kw)
        self.assertEqual(kw["output_config"]["format"]["type"], "json_schema")
        self.assertIn("Event: Katsucon", kw["messages"][0]["content"])
        usage = db.one(self.conn, "SELECT agent, cost_usd, detail FROM api_usage WHERE provider='anthropic'")
        self.assertIsNotNone(usage)
        self.assertEqual(usage["agent"], "seo")
        self.assertGreater(usage["cost_usd"], 0)

    def test_an_opus_override_goes_through_the_fallback_beta(self):
        os.environ["SEO_MODEL"] = "claude-opus-5"
        config.reset()
        self.photo()
        fake = FakeClaude()
        photo_text.write_all(self.conn, dry_run=False, client=fake)
        self.assertEqual(len(fake.calls), 1)
        path, kw = fake.calls[0]
        self.assertEqual(path, "beta")
        self.assertEqual((kw["fallbacks"], kw["betas"], kw["thinking"]), ("default", ["server-side-fallback-2026-07-01"], {"type": "adaptive"}))

    def test_answers_that_break_a_rule_are_replaced_by_the_template(self):
        bad = {
            "long alt": {"alt": "A cosplayer " + "in a long red cape " * 8},
            "price": {"description": "Portraits from $150 per hour at Katsucon."},
            "affiliation": {"title": "Official photographer of Katsucon 2025"},
            "address": {"alt": "Cosplayer outside 123 Main Street at Katsucon 2025"},
            "a name": {"alt": "Cosplayer Jane Doe posing at Katsucon 2025"},
            "a stranger's handle": {"alt": "Cosplay portrait of @someone.else at Katsucon 2025"},
        }
        for why, change in bad.items():
            with self.subTest(why):
                self.conn.execute("DELETE FROM photo_seo")
                pid = self.photo()
                answer = {**GOOD, **change}
                stats = photo_text.write_all(self.conn, dry_run=False, client=FakeClaude(answer=answer))
                r = self.row(pid)
                self.assert_public(r)
                self.assertEqual(r["model"], "template", why)
                self.assertGreaterEqual(stats["fell_back"], 1)

    def test_a_dash_is_tidied_into_a_comma(self):
        pid = self.photo()
        photo_text.write_all(self.conn, dry_run=False,
                             client=FakeClaude(answer={**GOOD, "title": "Cosplay portrait — Katsucon 2025"}))
        r = self.row(pid)
        self.assert_public(r)
        self.assertEqual(r["title"], "Cosplay portrait, Katsucon 2025")

    def test_keywords_cannot_bring_in_a_city_or_a_name(self):
        pid = self.photo()
        photo_text.write_all(self.conn, dry_run=False, client=FakeClaude(answer={
            **GOOD, "keywords": ["baltimore cosplay", "jane doe", "katsucon 2025", "anime convention photography", "cosplay portrait"]}))
        kws = json.loads(self.row(pid)["keywords"])
        self.assertTrue(kws)
        self.assertIn("katsucon 2025", kws)
        self.assertIn("anime convention photography", kws)
        self.assertFalse([k for k in kws if "baltimore" in k or "jane" in k], kws)
        few = photo_text.merge_keywords(["event photography"], photo_text.gather(self.conn, pid))
        self.assertTrue(5 <= len(few) <= 10, few)

    def test_refusal_cap_and_failure_all_fall_back_to_the_template(self):
        a = self.photo()
        photo_text.write_all(self.conn, dry_run=False, client=FakeClaude(stop="refusal"))
        self.assertEqual(self.row(a)["model"], "template")
        self.assertEqual(self.spent(), 1, "a refused call still costs and is still recorded")
        b = self.photo()
        os.environ["AI_MONTHLY_CAP_USD"] = "0"
        config.reset()
        capped = FakeClaude()
        stats = photo_text.write_all(self.conn, dry_run=False, client=capped)
        self.assertEqual(capped.calls, [], "no call once the cap is reached")
        self.assertIn("cap", stats["stopped"])
        self.assertEqual(self.row(b)["model"], "template")
        os.environ["AI_MONTHLY_CAP_USD"] = "20"
        config.reset()
        self.conn.execute("DELETE FROM photo_seo")
        broken = FakeClaude(error=ConnectionError("network down"))
        stats = photo_text.write_all(self.conn, dry_run=False, client=broken)
        self.assertEqual(len(broken.calls), 1, "after one failure the rest of the run uses the template")
        self.assertEqual(stats["written"], 2)
        self.assertEqual(db.one(self.conn, "SELECT kind FROM errors WHERE agent='seo'")["kind"], "seo_text")

    def test_a_row_chris_corrected_is_never_rewritten(self):
        pid = self.photo()
        photo_text.write_all(self.conn, dry_run=True)
        self.assertIsNone(photo_text.edit(self.conn, pid, alt="Cosplayer with a red cape by the window"))
        fake = FakeClaude()
        stats = photo_text.write_all(self.conn, dry_run=False, client=fake)
        self.assertEqual(fake.calls, [])
        self.assertEqual(stats["edited"], 1)
        r = self.row(pid)
        self.assertEqual(r["alt"], "Cosplayer with a red cape by the window")
        self.assertIsNotNone(r["edited_at"])
        photo_text.save(self.conn, pid, {**GOOD, "alt": "overwritten"}, "claude-haiku-4-5")
        self.assertEqual(self.row(pid)["alt"], "Cosplayer with a red cape by the window")

    def test_chris_edits_pass_the_hard_rules(self):
        pid = self.photo()
        self.credit(pid, handle="@kat.cos")
        photo_text.write_all(self.conn, dry_run=True)
        before = self.row(pid)["alt"]
        for bad in ("Cosplay portrait, $40 prints", "Cosplay portrait — Katsucon", "x" * 130, "Cosplayer at 12 Oak Street",
                    "Cosplay portrait of @nobody", ""):
            with self.subTest(bad):
                self.assertTrue(photo_text.edit(self.conn, pid, alt=bad))
                self.assertEqual(self.row(pid)["alt"], before)
        self.assertIsNone(photo_text.edit(self.conn, pid, alt="Cosplay portrait of @kat.cos in the Grand Ballroom"))


# ------------------------------------------------------------------ the agent and the site check

def pages(**override):
    good = ('<!doctype html><html><head><title>Event Caliber</title><meta name="description" content="Event photography.">'
            '</head><body><h1>Every room</h1><img src="/a.jpg" alt="Cosplay portrait"></body></html>')
    out = {f"{BASE}{p}": (200, good) for p in site_check.HTML_PATHS}
    out[f"{BASE}/sitemap.xml"] = (200, seo.sitemap_xml(BASE, seo.DEFAULT_PAGES))
    out[f"{BASE}/robots.txt"] = (200, seo.robots_txt(BASE))
    out.update({f"{BASE}{k}": v for k, v in override.items()})
    return out


class FakeSite:
    def __init__(self, table):
        self.table = table
        self.calls = []

    def __call__(self, url):
        self.calls.append(url)
        result = self.table.get(url, (404, "not found"))
        if isinstance(result, Exception):
            raise result
        return result


class Agent(SeoCase):
    def test_dry_run_uses_the_template_and_checks_nothing(self):
        pid = self.photo()
        fake, site = FakeClaude(), FakeSite(pages())
        summary = seo_agent.run(self.ctx(dry_run=True), client=fake, transport=site)
        self.assertTrue(summary.startswith("DRY RUN"))
        self.assertIn("would GET 6 pages on https://eventcaliber.com", summary)
        self.assertEqual(fake.calls, [])
        self.assertEqual(site.calls, [])
        self.assertEqual(self.spent(), 0)
        self.assertEqual(self.row(pid)["model"], "template")
        self.assertEqual(db.one(self.conn, "SELECT COUNT(*) n FROM site_checks")["n"], 0)

    def test_live_site_check_records_every_page_and_an_error_for_each_failure(self):
        bad_privacy = ('<html><head><title>Privacy</title><meta name="description" content="d"></head>'
                       '<body><p>no heading</p><img src="/x.jpg"></body></html>')
        site = FakeSite(pages(**{"/privacy/": (200, bad_privacy), "/sitemap.xml": (404, "nope")}))
        summary = seo_agent.run(self.ctx(dry_run=False), client=FakeClaude(), transport=site)
        self.assertIn("site check: 4 of 6 pages ok", summary)
        self.assertEqual(site.calls, [f"{BASE}{p}" for p in site_check.PATHS])
        rows = {r["path"]: r for r in site_check.latest(self.conn)}
        self.assertEqual(len(rows), 6)
        self.assertEqual(rows["/"]["ok"], 1)
        self.assertEqual((rows["/"]["title_ok"], rows["/"]["description_ok"], rows["/"]["h1_ok"], rows["/"]["alt_ok"]), (1, 1, 1, 1))
        self.assertEqual((rows["/privacy/"]["ok"], rows["/privacy/"]["h1_ok"], rows["/privacy/"]["alt_ok"]), (0, 0, 0))
        self.assertEqual(rows["/sitemap.xml"]["status_code"], 404)
        self.assertIsNone(rows["/sitemap.xml"]["title_ok"])
        errors = [r["message"] for r in db.rows(self.conn, "SELECT message FROM errors WHERE agent='seo' AND kind='site_check'")]
        self.assertEqual(len(errors), 2)
        self.assertTrue(any("/privacy/" in e and "no h1 heading" in e for e in errors), errors)

    def test_noindex_unreachable_and_a_closed_robots_file_fail(self):
        noindex = pages()[f"{BASE}/"][1].replace("</head>", '<meta name="robots" content="noindex"></head>')
        site = FakeSite(pages(**{"/": (200, noindex), "/book/": ConnectionError("down"),
                                 "/robots.txt": (200, "User-agent: *\nDisallow: /\n")}))
        res = site_check.run_check(self.conn, transport=site)
        self.assertEqual(res["failed"], 3)
        by = {r["path"]: r for r in res["results"]}
        self.assertIn("noindex", " ".join(by["/"]["problems"]))
        self.assertEqual(by["/book/"]["status"], 0)
        self.assertIn("could not be reached (ConnectionError)", by["/book/"]["problems"])
        self.assertIn("blocks the whole site (Disallow: /)", by["/robots.txt"]["problems"])

    def test_the_real_site_build_passes_the_check(self):
        """At the consumer: the pages site/build.py writes, served as the Worker would serve them."""
        out = build.build(None, build.SitePhotos(), out=self.root / "dist", preview=False)
        table = {f"{BASE}{p}": (200, (out / (p.strip("/") + "/index.html" if p != "/" else "index.html")).read_text())
                 for p in site_check.HTML_PATHS}
        table[f"{BASE}/sitemap.xml"] = (200, seo.sitemap_xml(BASE, seo.DEFAULT_PAGES))
        table[f"{BASE}/robots.txt"] = (200, seo.robots_txt(BASE))
        res = site_check.run_check(self.conn, transport=FakeSite(table))
        self.assertEqual(res["checked"], 6)
        self.assertEqual([(r["path"], r["problems"]) for r in res["results"] if not r["ok"]], [])
        preview = build.build(None, build.SitePhotos(), out=self.root / "preview", preview=True)
        self.assertIn("noindex", " ".join(site_check.check_html(200, (preview / "index.html").read_text())["problems"]))

    def test_runner_end_to_end_starts_in_dry_run(self):
        self.photo()
        self.assertEqual(runner.run("seo", seo_agent.run), runner.EXIT_OK)
        row = db.one(self.conn, "SELECT ok, dry_run, summary FROM agent_runs WHERE agent='seo'")
        self.assertIsNotNone(row)
        self.assertEqual((row["ok"], row["dry_run"]), (1, 1))
        self.assertIn("1 written", row["summary"])
        self.assertEqual(self.spent(), 0)


class Dashboard(SeoCase):
    def setUp(self):
        super().setUp()
        from convention_social.dashboard import learner_seo_routes
        from convention_social.dashboard.app import COOKIE, conn_dep, create_app, make_token, render, require_user
        os.environ["DASHBOARD_PASSWORD_HASH"] = auth.hash_password("correct horse")
        config.reset()
        app = create_app()
        learner_seo_routes.register(app, require_user, conn_dep, render)
        self.client = TestClient(app)
        self.cookie = (COOKIE, make_token("chris"))

    def test_needs_sign_in(self):
        self.assertEqual(self.client.get("/seo", follow_redirects=False).status_code, 307)
        self.assertEqual(self.client.post("/seo/1", data={"alt": "x"}).status_code, 401)

    def test_page_and_edit(self):
        pid = self.photo()
        photo_text.write_all(self.conn, dry_run=True)
        site_check.run_check(self.conn, transport=FakeSite(pages(**{"/book/": (500, "")})))
        self.client.cookies.set(*self.cookie)
        r = self.client.get("/seo")
        self.assertEqual(r.status_code, 200)
        self.assertIn("<main>", r.text)
        self.assertIn("cosplay-portrait-katsucon-2025", r.text)
        self.assertIn("answered 500", r.text)
        ok = self.client.post(f"/seo/{pid}", data={"alt": "Cosplayer with a red cape by a tall window"}, follow_redirects=False)
        self.assertEqual(ok.status_code, 303)
        self.assertIn("msg=saved", ok.headers["location"])
        row = self.row(pid)
        self.assertEqual(row["alt"], "Cosplayer with a red cape by a tall window")
        self.assertIsNotNone(row["edited_at"])
        self.assertEqual(row["title"], "Cosplay portrait at Katsucon 2025", "a blank title keeps the old one")
        refused = self.client.post(f"/seo/{pid}", data={"alt": "Prints from $40"}, follow_redirects=False)
        self.assertIn("msg=refused", refused.headers["location"])
        self.assertEqual(self.row(pid)["alt"], "Cosplayer with a red cape by a tall window")
        shown = self.client.get(refused.headers["location"])
        self.assertIn("Not saved", shown.text)
        self.assertEqual(self.client.post("/seo/999", data={"alt": "x"}).status_code, 404)

    def test_empty_pages_render(self):
        self.client.cookies.set(*self.cookie)
        for path in ("/seo", "/learner"):
            r = self.client.get(path)
            self.assertEqual(r.status_code, 200, path)
            self.assertIn("<main>", r.text)


if __name__ == "__main__":
    import unittest
    unittest.main()
