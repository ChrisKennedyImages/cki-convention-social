// The eventcaliber.com Worker against an in-memory D1 and R2. Run: node tests/worker_test.mjs (CI runs it).
import assert from "node:assert/strict";
import worker from "../worker/index.js";

class FakeD1 {
  constructor() { this.quotes = []; this.days = new Set(); this.unsubs = []; }
  prepare(sql) {
    const db = this;
    let args = [];
    const stmt = {
      bind(...a) { args = a; return stmt; },
      async first() {
        if (sql.includes("FROM unsubscribes")) return { n: db.unsubs.filter((u) => u.ip === args[0] && u.received_at > args[1]).length };
        if (sql.includes("COUNT(*)")) return { n: db.quotes.filter((q) => q.ip === args[0] && q.received_at > args[1]).length };
        return null;
      },
      async all() {
        if (sql.includes("FROM unsubscribes")) return { results: [...db.unsubs] };
        if (sql.includes("FROM quote_requests")) return { results: [...db.quotes] };
        if (sql.includes("FROM booked_days")) return { results: [...db.days].filter((d) => d >= args[0]).sort().map((day) => ({ day })) };
        return { results: [] };
      },
      async run() {
        if (sql.startsWith("INSERT INTO quote_requests")) db.quotes.push({ id: args[0], received_at: args[1], ip: args[2], body: args[3] });
        else if (sql.startsWith("DELETE FROM quote_requests")) db.quotes = db.quotes.filter((q) => q.id !== args[0]);
        else if (sql.startsWith("DELETE FROM booked_days")) db.days.clear();
        else if (sql.startsWith("INSERT OR IGNORE INTO booked_days")) db.days.add(args[0]);
        else if (sql.startsWith("INSERT OR IGNORE INTO unsubscribes")) {
          if (!db.unsubs.some((u) => u.token === args[0])) db.unsubs.push({ token: args[0], received_at: args[1], ip: args[2] });
        } else if (sql.startsWith("DELETE FROM unsubscribes")) db.unsubs = db.unsubs.filter((u) => u.token !== args[0]);
        return {};
      },
    };
    return stmt;
  }
}

const pushes = [];
globalThis.fetch = async (url, init) => { pushes.push({ url: String(url), body: init?.body, headers: init?.headers || {} }); return new Response("ok"); };
class FakeR2 {
  // strings stay strings (the JSON the Worker keeps); anything else is kept as its bytes, with its metadata
  constructor() { this.store = new Map(); this.meta = new Map(); }
  async get(key) {
    if (!this.store.has(key)) return null;
    const value = this.store.get(key);
    const { httpMetadata = {}, customMetadata = {} } = this.meta.get(key) || {};
    const text = typeof value === "string" ? value : new TextDecoder().decode(value);
    return { text: async () => text, json: async () => JSON.parse(text), body: value, httpEtag: "x", httpMetadata, customMetadata,
             size: typeof value === "string" ? value.length : value.byteLength,
             writeHttpMetadata(h) { if (httpMetadata.contentType) h.set("content-type", httpMetadata.contentType); } };
  }
  async put(key, body, options = {}) {
    this.store.set(key, typeof body === "string" ? body : new Uint8Array(await new Response(body).arrayBuffer()));
    this.meta.set(key, { httpMetadata: options.httpMetadata || {}, customMetadata: options.customMetadata || {} });
  }
  async delete(key) { this.store.delete(key); this.meta.delete(key); }
  async list({ prefix = "", limit = 1000, include = [] } = {}) {
    const keys = [...this.store.keys()].filter((k) => k.startsWith(prefix)).sort();
    const objects = keys.slice(0, limit).map((key) => {
      const v = this.store.get(key);
      const m = this.meta.get(key) || {};
      return { key, size: typeof v === "string" ? v.length : v.byteLength, uploaded: new Date(),
               ...(include.includes("customMetadata") ? { customMetadata: m.customMetadata || {} } : {}),
               ...(include.includes("httpMetadata") ? { httpMetadata: m.httpMetadata || {} } : {}) };
    });
    return { objects, truncated: keys.length > limit };
  }
}
const env = { DB: new FakeD1(), UPLOAD_TOKEN: "tok", NTFY_TOPIC: "topic-x", DASHBOARD_URL: "https://mac-mini.example:8443",
              MEDIA: new FakeR2(), ASSETS: { fetch: async () => new Response("site") } };
const base = "https://eventcaliber.com";
const form = (fields) => {
  const f = new FormData();
  for (const [k, v] of Object.entries(fields)) (Array.isArray(v) ? v : [v]).forEach((x) => f.append(k, x));
  return f;
};
const post = (fields, headers = {}) => worker.fetch(new Request(`${base}/api/quote`, { method: "POST", body: form(fields),
  headers: { "cf-connecting-ip": "1.2.3.4", ...headers } }), env);
let checks = 0;
const ok = (cond, msg) => { assert.ok(cond, msg); checks++; };

// a good request is stored, pushed without personal details, and lands on /thanks/
let r = await post({ name: "Dana", email: "dana@example.org", event_name: "Sample Con", start_date: "2027-03-05",
                     coverage: ["backstage", "on_site_delivery", "nonsense"], phone: "555 0100" });
ok(r.status === 303 && r.headers.get("location").endsWith("/thanks/"), "good request redirects to thanks");
ok(env.DB.quotes.length === 1, "stored");
const body = JSON.parse(env.DB.quotes[0].body);
ok(JSON.stringify(body.coverage) === JSON.stringify(["backstage", "on_site_delivery"]), "only known coverage kept");
ok(pushes.length === 1 && pushes[0].url.endsWith("/topic-x"), "one push");
ok(!pushes[0].body.includes("Dana") && !pushes[0].body.includes("dana@") && !pushes[0].body.includes("555"), "push carries no personal details");
ok(pushes[0].headers.Click === "https://mac-mini.example:8443/inquiries", "the push opens the requests page (2026-10-13)");
delete env.DASHBOARD_URL;
await post({ name: "Eve", email: "eve@example.org", event_name: "Other Con" });
ok(pushes.length === 2 && !("Click" in pushes[1].headers), "no dashboard address, no Click");
env.DASHBOARD_URL = "https://mac-mini.example:8443";
env.DB.quotes.pop();                                   // Eve's request leaves the counts below as they were

// the honeypot drops quietly; a missing email is refused; the hourly limit holds
r = await post({ name: "Bot", email: "b@example.org", website: "http://spam" });
ok(r.status === 303 && env.DB.quotes.length === 1, "honeypot dropped");
r = await post({ name: "No mail" });
ok(r.status === 303 && r.headers.get("location").includes("error=missing") && env.DB.quotes.length === 1, "missing email refused");
for (let i = 0; i < 6; i++) await post({ name: "N", email: `n${i}@example.org` });
ok(env.DB.quotes.length === 5, "rate limit: five an hour per address");

// the Mini pulls with the token, acks, and the rows are gone
r = await worker.fetch(new Request(`${base}/api/inquiries`), env);
ok(r.status === 403, "pull needs the token");
r = await worker.fetch(new Request(`${base}/api/inquiries`, { headers: { authorization: "Bearer tok" } }), env);
const pulled = (await r.json()).inquiries;
ok(pulled.length === 5 && pulled[0].name === "Dana" && pulled[0].id, "pulled");
r = await worker.fetch(new Request(`${base}/api/inquiries/ack`, { method: "POST", headers: { authorization: "Bearer tok" },
  body: JSON.stringify({ ids: pulled.map((p) => p.id) }) }), env);
ok((await r.json()).deleted === 5 && env.DB.quotes.length === 0, "acked rows deleted");

// availability: public dates only, written only with the token
r = await worker.fetch(new Request(`${base}/api/availability`, { method: "PUT", body: JSON.stringify({ booked: ["2099-01-02"] }) }), env);
ok(r.status === 403, "availability write needs the token");
r = await worker.fetch(new Request(`${base}/api/availability`, { method: "PUT", headers: { authorization: "Bearer tok" },
  body: JSON.stringify({ booked: ["2099-01-02", "2099-01-03", "not a date", "2000-01-01"] }) }), env);
ok((await r.json()).booked === 3, "bad dates dropped");
r = await worker.fetch(new Request(`${base}/api/availability`), env);
ok(JSON.stringify((await r.json()).booked) === JSON.stringify(["2099-01-02", "2099-01-03"]), "past dates hidden, no names");

// media and the site
r = await worker.fetch(new Request(`${base}/m/private/backups/x.gz`), env);
ok(r.status === 404, "private never served");
r = await worker.fetch(new Request(`${base}/m/convention-social/a.jpg`, { method: "PUT", headers: { "content-type": "image/jpeg" }, body: "x" }), env);
ok(r.status === 403, "upload needs the token");
r = await worker.fetch(new Request(`${base}/`), env);
ok((await r.text()) === "site", "everything else is the site");
r = await worker.fetch(new Request(`${base}/api/nothing`), env);
ok(r.status === 404, "unknown api 404");
// opt-outs from outreach emails: a page with one button, a one-click POST, the token stored, never the address
const tokA = "a".repeat(32), tokB = "b".repeat(32), tokC = "c".repeat(32);
const unsub = (path, init = {}) => worker.fetch(new Request(`${base}${path}`, { ...init,
  headers: { "cf-connecting-ip": "5.6.7.8", ...(init.headers || {}) } }), env);
r = await unsub(`/unsubscribe?t=${tokA}`);
let page = await r.text();
ok(r.status === 200 && page.includes('action="/api/unsubscribe"') && page.includes(tokA), "opt-out page has the confirm button");
ok(env.DB.unsubs.length === 0, "opening the page stores nothing");
r = await unsub("/unsubscribe?t=not-a-token");
ok(r.status === 400, "a broken opt-out link is refused");
r = await unsub("/api/unsubscribe", { method: "POST", body: form({ t: tokA }) });
ok(r.status === 200 && (await r.text()).includes("unsubscribed") && env.DB.unsubs.length === 1, "the button stores the token");
r = await unsub("/api/unsubscribe", { method: "POST", body: form({ t: tokA }) });
ok(env.DB.unsubs.length === 1, "the same token twice is stored once");
r = await unsub(`/unsubscribe?t=${tokB}`, { method: "POST", body: "List-Unsubscribe=One-Click",
  headers: { "content-type": "application/x-www-form-urlencoded" } });
ok(r.status === 200 && env.DB.unsubs.some((u) => u.token === tokB), "one-click opt-out from a mail client is stored");
r = await unsub("/api/unsubscribe", { method: "POST", body: JSON.stringify({ t: tokC }),
  headers: { "content-type": "application/json", accept: "application/json" } });
ok(r.status === 200 && (await r.json()).ok === true, "JSON opt-out answers JSON");
r = await unsub("/api/unsubscribe", { method: "POST", body: form({ t: "x@example.org" }) });
ok(r.status === 400 && env.DB.unsubs.length === 3, "an address instead of a token is refused");
r = await unsub("/api/unsubscribe");
ok(r.status === 405, "GET on the store is not allowed");
for (let i = 0; i < 25; i++) {
  await worker.fetch(new Request(`${base}/api/unsubscribe`, { method: "POST", body: form({ t: i.toString(16).padStart(32, "d") }),
    headers: { "cf-connecting-ip": "9.9.9.9" } }), env);
}
ok(env.DB.unsubs.filter((u) => u.ip === "9.9.9.9").length === 20, "rate limit: twenty opt-outs an hour per address");
r = await worker.fetch(new Request(`${base}/api/unsubscribes`), env);
ok(r.status === 403, "pulling opt-outs needs the token");
r = await worker.fetch(new Request(`${base}/api/unsubscribes`, { headers: { authorization: "Bearer tok" } }), env);
const outs = (await r.json()).unsubscribes;
ok(outs.length === 23 && outs.every((u) => /^[a-f0-9]{32}$/.test(u.token) && !("ip" in u)), "the Mini pulls tokens only");
r = await worker.fetch(new Request(`${base}/api/unsubscribes/ack`, { method: "POST", headers: { authorization: "Bearer tok" },
  body: JSON.stringify({ tokens: [tokA, tokB, "junk"] }) }), env);
ok((await r.json()).deleted === 2 && env.DB.unsubs.length === 21, "acked opt-outs deleted");
r = await worker.fetch(new Request(`${base}/api/unsubscribes/ack`, { method: "POST", body: JSON.stringify({ tokens: [tokC] }) }), env);
ok(r.status === 403 && env.DB.unsubs.length === 21, "ack needs the token");
// the outside watch (7.4, 2026-10-13): the Mini posts a heartbeat; the cron tells the phone when it stops
const realNow = Date.now;
const T0 = Date.parse("2026-10-13T12:00:00Z");
Date.now = () => T0;
const cron = () => worker.scheduled({ scheduledTime: Date.now(), cron: "*/30 * * * *" }, env, { waitUntil() {} });
const beat = (init = {}) => worker.fetch(new Request(`${base}/api/heartbeat`, { method: "POST", headers: { authorization: "Bearer tok" }, ...init }), env);
pushes.length = 0;
await cron();
ok(pushes.length === 0, "no heartbeat ever: the watch says nothing");
r = await worker.fetch(new Request(`${base}/api/heartbeat`, { method: "POST" }), env);
ok(r.status === 403, "the heartbeat needs the token");
r = await worker.fetch(new Request(`${base}/api/heartbeat`, { headers: { authorization: "Bearer tok" } }), env);
ok(r.status === 405, "a GET is not a heartbeat");
r = await beat();
ok(r.status === 200 && (await r.json()).at === "2026-10-13T12:00:00.000Z", "the heartbeat is stored with its time");
ok(env.MEDIA.store.has("private/heartbeat.json"), "under private/, never served");
await cron();
ok(pushes.length === 0, "a fresh heartbeat: quiet");
Date.now = () => T0 + 3 * 3600e3;
await cron();
ok(pushes.length === 1 && pushes[0].body.includes("has not checked in since 2026-10-13T12:00:00.000Z"), "three hours of silence: one urgent ping");
ok(pushes[0].headers.Priority === "urgent" && pushes[0].headers.Click === "https://mac-mini.example:8443", "urgent, and it opens the dashboard");
await cron();
ok(pushes.length === 1, "said once, not every half hour");
Date.now = () => T0 + 4 * 3600e3;
await beat();
await cron();
ok(pushes.length === 2 && pushes[1].body.includes("The Mini is back"), "a fresh heartbeat after the alert: it is back");
await cron();
ok(pushes.length === 2, "and that is said once too");
Date.now = () => T0 + 7 * 3600e3;
await cron();
ok(pushes.length === 3, "silent again later: a new alert");
r = await worker.fetch(new Request(`${base}/api/heartbeat/test`, { method: "POST", headers: { authorization: "Bearer tok" } }), env);
ok(r.status === 200 && (await r.json()).sent === true && pushes.length === 4 && pushes[3].body.includes("(test)"), "Test the outside watch sends the alert at once, marked as a test");
r = await worker.fetch(new Request(`${base}/api/heartbeat/test`, { method: "POST" }), env);
ok(r.status === 403, "the test needs the token too");
Date.now = realNow;

// www. is the same site (2026-10-14): one address for the search engines, so www. answers 301 to the apex for good,
// path and query kept, before any route; the apex itself serves the site
r = await worker.fetch(new Request("https://www.eventcaliber.com/about/?x=1"), env);
ok(r.status === 301 && r.headers.get("location") === "https://eventcaliber.com/about/?x=1", "www. answers 301 to the apex, path and query kept");
r = await worker.fetch(new Request("https://www.eventcaliber.com/api/availability"), env);
ok(r.status === 301 && r.headers.get("location") === "https://eventcaliber.com/api/availability", "the API too, before any route");
r = await worker.fetch(new Request(`${base}/about/`), env);
ok(r.status === 200 && (await r.text()) === "site", "the apex serves the site");

// Post to Event Caliber (2026-10-15): the iPhone's share sheet sends one photo and a line with SEND_TOKEN in a header;
// the photo waits under private/sends/ (never served) until the Mini pulls it with its own token and deletes it
const JPEG = Uint8Array.from([0xff, 0xd8, 0xff, 0xe0, 0, 16, 74, 70, 73, 70, 0, 1, 1, 1, 2, 3, 4, 5, 6, 7]);
const PNG = Uint8Array.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0, 0, 0, 13, 73, 72, 68, 82]);
const HEIC = Uint8Array.from([0, 0, 0, 24, 0x66, 0x74, 0x79, 0x70, 0x68, 0x65, 0x69, 0x63, 0, 0, 0, 0, 0x6d, 0x69, 0x66, 0x31]);
const sendToken = "s".repeat(43);
env.SEND_TOKEN = sendToken;
const sendForm = (bytes, { note, type = "image/jpeg", field = "photo", name = "IMG_0001.jpg" } = {}) => {
  const f = new FormData();
  if (bytes) f.append(field, new File([bytes], name, { type }));
  if (note !== undefined) f.append("note", note);
  return f;
};
const send = (body, headers = { authorization: `Bearer ${sendToken}` }, method = "POST") =>
  worker.fetch(new Request(`${base}/api/send`, { method, body, headers: { "cf-connecting-ip": "7.7.7.7", ...headers } }), env);
const waiting = () => [...env.MEDIA.store.keys()].filter((k) => k.startsWith("private/sends/"));
r = await send(sendForm(JPEG), {});
ok(r.status === 403 && (await r.text()).startsWith("Not received") && waiting().length === 0, "no token: refused, nothing stored");
r = await send(sendForm(JPEG), { authorization: "Bearer wrong" });
ok(r.status === 403 && waiting().length === 0, "a wrong token: refused");
r = await send(sendForm(JPEG), { authorization: "Bearer tok" });
ok(r.status === 403 && waiting().length === 0, "the Mini's upload token is not the phone's: refused");
r = await send(sendForm(JPEG), { "x-send-token": sendToken });
ok(r.status === 403, "the token goes in Authorization, nowhere else");
r = await worker.fetch(new Request(`${base}/api/send?token=${sendToken}`, { method: "POST", body: sendForm(JPEG) }), env);
ok(r.status === 403 && waiting().length === 0, "never in the address, where a log keeps it");
delete env.SEND_TOKEN;
r = await send(sendForm(JPEG));
ok(r.status === 503 && (await r.text()).includes("not set up") && waiting().length === 0, "no SEND_TOKEN on the Worker: refused (fail closed)");
env.SEND_TOKEN = sendToken;
r = await send(null, { authorization: `Bearer ${sendToken}` }, "GET");
ok(r.status === 405, "a GET sends nothing");
r = await send(sendForm(Uint8Array.from([0x25, 0x50, 0x44, 0x46, 0x2d, 0x31, 0x2e, 0x34, 0, 0, 0, 0]), { type: "image/jpeg" }));
ok(r.status === 415 && (await r.text()).includes("JPEG, PNG or HEIC") && waiting().length === 0, "a PDF called a JPEG: refused by its bytes");
r = await send(sendForm(new TextEncoder().encode("GIF89a and more bytes"), { type: "image/gif", name: "a.gif" }));
ok(r.status === 415 && waiting().length === 0, "a GIF: refused (wrong type)");
r = await send(sendForm(null, { note: "no photo" }));
ok(r.status === 400 && (await r.text()).includes("no photo") && waiting().length === 0, "no photo in it: refused");
const big = new Uint8Array(40 * 1024 * 1024 + 1);
big.set(JPEG);
r = await send(sendForm(big));
ok(r.status === 413 && (await r.text()).includes("40 MB") && waiting().length === 0, "over 40 MB: refused");
let bodyRead = false;                                  // a request stand-in: Node's Request may drop a content-length set by hand
r = await worker.fetch({ url: `${base}/api/send`, method: "POST", formData: async () => { bodyRead = true; return new FormData(); },
  headers: new Headers({ authorization: `Bearer ${sendToken}`, "content-length": String(60 * 1024 * 1024) }) }, env);
ok(r.status === 413 && !bodyRead && waiting().length === 0, "a body that says it is over the limit is refused before it is read");
r = await send(sendForm(JPEG, { note: "  the main hall,\n  before the doors  " }));
let said = await r.text();
ok(r.status === 200 && said.startsWith("Received.") && said.length < 120, "a JPEG is received, in a short line the Shortcut shows");
ok(waiting().length === 1 && /^private\/sends\/\d{13}-[0-9a-f]{16}$/.test(waiting()[0]), "stored under the private prefix, a random name");
const stored = env.MEDIA.store.get(waiting()[0]);
ok(stored instanceof Uint8Array && stored.length === JPEG.length && stored.every((b, i) => b === JPEG[i]), "the bytes as sent");
const meta = env.MEDIA.meta.get(waiting()[0]);
ok(meta.customMetadata.note === "the main hall, before the doors" && meta.customMetadata.type === "image/jpeg", "his line, on one line, and the type by its bytes");
r = await worker.fetch(new Request(`${base}/m/${waiting()[0]}`), env);
ok(r.status === 404, "/m/ never serves a send");
r = await worker.fetch(new Request(`${base}/m/${encodeURIComponent(waiting()[0])}`), env);
ok(r.status === 404, "nor its encoded name");
r = await send(sendForm(PNG, { type: "image/png", name: "a.png" }));
ok(r.status === 200 && waiting().length === 2, "a PNG is received");
r = await send(sendForm(HEIC, { type: "application/octet-stream", name: "IMG_0002.HEIC", note: "x".repeat(400) }));
ok(r.status === 200 && waiting().length === 3, "a HEIC is received, whatever type the phone called it");
ok(env.MEDIA.meta.get(waiting()[2]).customMetadata.type === "image/heic", "known as HEIC by its bytes");
ok(env.MEDIA.meta.get(waiting()[2]).customMetadata.note.length === 140, "a long line is cut to 140");
// the Mini pulls with its own token: the list, each photo, then the delete
r = await worker.fetch(new Request(`${base}/api/sends`), env);
ok(r.status === 403, "listing the sends needs the Mini's token");
r = await worker.fetch(new Request(`${base}/api/sends`, { headers: { authorization: `Bearer ${sendToken}` } }), env);
ok(r.status === 403, "the phone's token can send, never read");
r = await worker.fetch(new Request(`${base}/api/sends`, { headers: { authorization: "Bearer tok" } }), env);
const sends = (await r.json()).sends;
// found by type, not by place: a send's name starts with its millisecond, and two sends in the same millisecond
// list in the order of their random part (2026-10-16: a CI run failed "the Mini fetches the photo itself" on it)
const jpeg = sends.find((s) => s.type === "image/jpeg"), png = sends.find((s) => s.type === "image/png");
ok(sends.length === 3 && jpeg?.note === "the main hall, before the doors" && jpeg?.size === JPEG.length,
   "the Mini lists each send with its line, type and size");
ok(sends.every((s) => /^\d{13}-[0-9a-f]{16}$/.test(s.id) && s.received_at), "each by its name, with when it came");
r = await worker.fetch(new Request(`${base}/api/sends/${png.id}`), env);
ok(r.status === 403, "a photo needs the Mini's token too");
r = await worker.fetch(new Request(`${base}/api/sends/${png.id}`, { headers: { authorization: "Bearer tok" } }), env);
const got = new Uint8Array(await r.arrayBuffer());
ok(r.status === 200 && r.headers.get("content-type") === "image/png" && got.length === PNG.length && got[1] === 0x50, "the Mini fetches the photo itself");
r = await worker.fetch(new Request(`${base}/api/sends/..%2Fheartbeat.json`, { headers: { authorization: "Bearer tok" } }), env);
ok(r.status === 400, "only a send's own name");
r = await worker.fetch(new Request(`${base}/api/sends/ack`, { method: "POST", headers: { authorization: `Bearer ${sendToken}` },
  body: JSON.stringify({ ids: [jpeg.id] }) }), env);
ok(r.status === 403 && waiting().length === 3, "the phone's token cannot delete");
r = await worker.fetch(new Request(`${base}/api/sends/ack`, { method: "POST", headers: { authorization: "Bearer tok" },
  body: JSON.stringify({ ids: [jpeg.id, png.id, "../heartbeat.json"] }) }), env);
ok((await r.json()).deleted === 2 && waiting().length === 1 && env.MEDIA.store.has("private/heartbeat.json"), "kept on the Mini: deleted here, nothing else");
// rate limited, and a Mini that is not pulling cannot fill the bucket
for (let i = 0; i < 30; i++) await send(sendForm(JPEG));
r = await send(sendForm(JPEG));
ok(r.status === 429 && (await r.text()).includes("an hour"), "twenty sends an hour, then refused with the reason");
ok(waiting().length === 18, "nothing over the limit was stored (one left from before, three sent earlier this hour)");
Date.now = () => realNow() + 2 * 3600e3;
r = await send(sendForm(JPEG));
ok(r.status === 200, "an hour later it takes photos again");
for (let i = 0; i < 40; i++) await send(sendForm(JPEG));
ok(waiting().length === 30, "never more than thirty waiting for the Mini");
r = await send(sendForm(JPEG));
ok(r.status === 503 && (await r.text()).includes("waiting"), "thirty waiting: refused, and it says the Mini has not picked them up");
Date.now = realNow;

// The team (2026-10-15): Chris's photographers send with tokens of their own. The Mini puts their hashes (never a name)
// at private/team.json; a phone without Shortcuts opens a one-time link that sets a cookie for the upload page.
for (const k of [...env.MEDIA.store.keys()]) if (k.startsWith("private/sends/") || k.startsWith("private/send-log")) env.MEDIA.store.delete(k);
const hex = async (t) => [...new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(t)))].map((b) => b.toString(16).padStart(2, "0")).join("");
const annaTok = "a".repeat(43), benTok = "b".repeat(43), joinCode = "j".repeat(32), oldCode = "o".repeat(32);
const putTeam = (body, auth = "Bearer tok") => worker.fetch(new Request(`${base}/api/team`, { method: "PUT", body: JSON.stringify(body),
  headers: { authorization: auth, "content-type": "application/json" } }), env);
const teamBody = async (benActive = true) => ({
  members: [{ id: 1, token_sha256: await hex(annaTok), active: true }, { id: 2, token_sha256: await hex(benTok), active: benActive }],
  joins: [{ code_sha256: await hex(joinCode), member_id: 1, expires_at: new Date(Date.now() + 86400e3).toISOString() },
          { code_sha256: await hex(oldCode), member_id: 1, expires_at: new Date(Date.now() - 1000).toISOString() }] });
r = await putTeam(await teamBody(), `Bearer ${sendToken}`);
ok(r.status === 403 && !env.MEDIA.store.has("private/team.json"), "the team list is the Mini's to write: the phone's token cannot");
r = await putTeam(await teamBody());
ok(r.status === 200 && env.MEDIA.store.has("private/team.json"), "the Mini writes the team list");
ok(!/anna|ben/i.test(env.MEDIA.store.get("private/team.json")), "the list at the site carries no name");
r = await putTeam({ members: [{ id: 3, token_sha256: "plain-token", active: true }] });
ok(r.status === 400, "anything but a hash is refused");
await putTeam(await teamBody());
r = await send(sendForm(JPEG, { note: "the green room" }), { authorization: `Bearer ${annaTok}` });
ok(r.status === 200 && waiting().length === 1, "a photographer's own token sends");
ok(env.MEDIA.meta.get(waiting()[0]).customMetadata.sender === "m1", "and the send says who, by number only");
r = await send(sendForm(JPEG), { authorization: `Bearer ${sendToken}` });
ok(r.status === 200 && env.MEDIA.meta.get(waiting()[1]).customMetadata.sender === "chris", "Chris's own token is Chris");
await putTeam(await teamBody(false));
r = await send(sendForm(JPEG), { authorization: `Bearer ${benTok}` });
ok(r.status === 403 && waiting().length === 2, "a photographer switched off: refused at once");
r = await send(sendForm(JPEG), { authorization: `Bearer ${"c".repeat(43)}` });
ok(r.status === 403, "a token nobody holds: refused");
delete env.SEND_TOKEN;
r = await send(sendForm(JPEG), { authorization: `Bearer ${annaTok}` });
ok(r.status === 200, "the team sends without Chris's own token set");
env.SEND_TOKEN = sendToken;
r = await worker.fetch(new Request(`${base}/api/sends`, { headers: { authorization: "Bearer tok" } }), env);
ok((await r.json()).sends.map((x) => x.sender).sort().join() === "chris,m1,m1", "the Mini lists who sent each, by number");
for (let i = 0; i < 20; i++) await send(sendForm(JPEG), { authorization: `Bearer ${annaTok}` });
r = await send(sendForm(JPEG), { authorization: `Bearer ${sendToken}` });
ok(r.status === 200, "the hourly limit is each sender's own: Anna's twenty do not stop Chris");
// a phone without Shortcuts: the one-time link, a button (a link preview fetches the page and uses nothing), a cookie
for (const k of [...env.MEDIA.store.keys()]) if (k.startsWith("private/sends/") || k.startsWith("private/send-log")) env.MEDIA.store.delete(k);
r = await worker.fetch(new Request(`${base}/join/${joinCode}`), env);
page = await r.text();
ok(r.status === 200 && page.includes('method="post"') && !r.headers.get("set-cookie"), "the link opens a page with a button; nothing is used yet");
ok(!page.includes(annaTok) && r.headers.get("referrer-policy") === "no-referrer", "no token on it, and it sends no referrer");
const join = (code, init = {}) => worker.fetch(new Request(`${base}/join`, { method: "POST", body: form({ code }),
  headers: { origin: base, ...(init.headers || {}) } }), env);
r = await join(oldCode);
ok(r.status === 403 && !r.headers.get("set-cookie"), "an expired link: refused");
r = await join(joinCode);
const cookie = (r.headers.get("set-cookie") || "").split(";")[0];
ok(r.status === 303 && r.headers.get("location") === "/upload", "the button opens the upload page");
ok(/HttpOnly/.test(r.headers.get("set-cookie")) && /Secure/.test(r.headers.get("set-cookie")) && /SameSite=Strict/.test(r.headers.get("set-cookie")),
   "the cookie is HttpOnly, Secure and SameSite=Strict");
ok(cookie.startsWith("ec_send=") && !cookie.includes(annaTok), "the cookie is a session of its own, never the Shortcut's token");
r = await join(joinCode);
ok(r.status === 403 && !r.headers.get("set-cookie"), "the link works once");
r = await worker.fetch(new Request(`${base}/upload`), env);
ok(r.status === 200 && (await r.text()).includes("Open the link you were sent"), "the upload page, without the cookie, only says how to get in");
r = await worker.fetch(new Request(`${base}/upload`, { headers: { cookie } }), env);
page = await r.text();
ok(r.status === 200 && page.includes('type="file"') && page.includes('accept="image/*"') && page.includes('name="note"'), "with it: one photo, a line, Send");
ok(page.includes('rel="manifest"') && !page.includes(cookie.split("=")[1]), "it installs to the home screen; the session is not on the page");
r = await worker.fetch(new Request(`${base}/upload/manifest.webmanifest`), env);
ok(r.status === 200 && (await r.json()).start_url === "/upload", "the home screen icon opens the upload page");
const cookieSend = (headers) => worker.fetch(new Request(`${base}/api/send`, { method: "POST", body: sendForm(JPEG, { note: "from the web" }),
  headers: { cookie, ...headers } }), env);
r = await cookieSend({ origin: base });
ok(r.status === 200 && env.MEDIA.meta.get(waiting()[0]).customMetadata.sender === "m1", "the page sends as its photographer");
r = await cookieSend({ origin: "https://elsewhere.example" });
ok(r.status === 403 && waiting().length === 1, "a page elsewhere cannot send with the cookie");
r = await cookieSend({});
ok(r.status === 403, "nor a request that says nothing of where it came from");
const teamOff = await teamBody(); teamOff.members[0].active = false;
await putTeam(teamOff);
r = await cookieSend({ origin: base });
ok(r.status === 403 && waiting().length === 1, "switched off: the phone's page stops too");
r = await worker.fetch(new Request(`${base}/upload`, { headers: { cookie } }), env);
ok((await r.text()).includes("Open the link you were sent"), "and the page says how to get back in");
r = await worker.fetch(new Request(`${base}/join/${joinCode}`), env);
ok((await r.text()).includes("Chris or Nic approves each one"), "outside, it is always Chris or Nic who approves (Chris, 2026-10-15)");
// 2026-10-24 audit: authed() compared the upload token with ===, the send token through sameSecret; one way for both
const source = (await import("node:fs")).readFileSync(new URL("../worker/index.js", import.meta.url), "utf8");
const authedSource = source.slice(source.indexOf("async function authed("), source.indexOf("\n}\n", source.indexOf("async function authed(")));
ok(authedSource.includes("await sameSecret(") && !authedSource.includes("==="), "the upload token is compared byte by byte to the end, like the send token");
ok(!/\bauthed\(request, env\)\)/.test(source.replace(/await authed\(request, env\)/g, "")), "every gate awaits the compare (a bare call would be a Promise, always true)");
r = await worker.fetch(new Request(`${base}/api/inquiries`, { headers: { authorization: "Bearer to" } }), env);
ok(r.status === 403, "a prefix of the token is not the token");
r = await worker.fetch(new Request(`${base}/api/inquiries`, { headers: { authorization: "tok" } }), env);
ok(r.status === 403, "the token without Bearer is not accepted");
console.log(`worker: ${checks} checks passed`);
