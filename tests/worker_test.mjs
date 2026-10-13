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
  constructor() { this.store = new Map(); }
  async get(key) {
    if (!this.store.has(key)) return null;
    const text = this.store.get(key);
    return { text: async () => text, json: async () => JSON.parse(text), body: text, httpEtag: "x", writeHttpMetadata() {} };
  }
  async put(key, body) { this.store.set(key, typeof body === "string" ? body : await new Response(body).text()); }
  async delete(key) { this.store.delete(key); }
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
console.log(`worker: ${checks} checks passed`);
