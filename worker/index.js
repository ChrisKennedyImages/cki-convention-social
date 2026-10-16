// eventcaliber.com: the website, quote requests, the public availability calendar and post images.
//
//   GET  /*                     the static site (binding ASSETS, built on the Mini by `bin/ccs site build`)
//   POST /api/quote             a quote request from the /book/ form: checked, stored in D1 (binding DB),
//                               a phone push with no personal details, then /thanks/
//   GET  /api/inquiries         the Mini pulls new requests (Bearer UPLOAD_TOKEN)
//   POST /api/inquiries/ack     the Mini confirms it has them; they are then deleted here
//   GET  /api/availability      booked dates only, no names (public)
//   PUT  /api/availability      the Mini replaces the booked dates (Bearer UPLOAD_TOKEN)
//   GET  /m/<key>               post images, public ONLY under convention-social/ (binding MEDIA, R2)
//   PUT  /m/<key>               the Mini uploads a post image or, under private/, the nightly backup
//   GET  /unsubscribe?t=<token> the opt-out page linked from every outreach email: one button, nothing stored yet
//   POST /unsubscribe?t=<token> a mail client's one-click opt-out (List-Unsubscribe-Post, RFC 8058): stored at once
//   POST /api/unsubscribe       the opt-out page's button: the token is stored in D1 (rate limited like /api/quote)
//   GET  /api/unsubscribes      the Mini pulls opt-out tokens (Bearer UPLOAD_TOKEN)
//   POST /api/unsubscribes/ack  the Mini confirms it has them; they are then deleted here
//   POST /api/heartbeat         the Mini checks in (Bearer UPLOAD_TOKEN); private/heartbeat.json in R2 (7.4, 2026-10-13)
//   POST /api/heartbeat/test    sends the outside watch's alert at once, marked as a test (Bearer UPLOAD_TOKEN)
//   POST /api/send              Post to Event Caliber (2026-10-15): the iPhone's share sheet sends one photo (form field
//                               "photo": JPEG, PNG or HEIC by its bytes, at most 40 MB) and an optional line ("note"),
//                               Bearer SEND_TOKEN. Kept under private/sends/ (never served) for the Mini; a short answer
//                               the Shortcut shows. Twenty an hour; never more than thirty waiting.
//   GET  /api/sends             the Mini lists the sends waiting (Bearer UPLOAD_TOKEN; the phone's token cannot read)
//   GET  /api/sends/<id>        the Mini fetches one (Bearer UPLOAD_TOKEN)
//   POST /api/sends/ack         the Mini kept them; they are deleted here (Bearer UPLOAD_TOKEN)
//   PUT  /api/team              the Mini writes the team (2026-10-15): each photographer's number, the SHA-256 of their
//                               send token and whether they are on, and one-time phone links by their hash; never a name
//   GET  /join/<code>           a photographer's one-time link: a page with one button (a link preview uses nothing)
//   POST /join                  the button: the link is used up and an HttpOnly cookie opens /upload on that phone
//   GET  /upload                the upload page for a phone without Shortcuts (one photo, a line, Send), cookie only
//   scheduled (cron, every 30 min): the outside watch. A heartbeat older than QUIET_MS and no alert yet: one urgent
//                               push "the Mini has not checked in since"; a fresh heartbeat after an alert: "back";
//                               no heartbeat ever: nothing. The only watch that does not live on the Mini.
//   Opt-outs carry only the random token from the email, never the address; the Mini maps it back.
//
// Secrets (wrangler secret put): UPLOAD_TOKEN, and optionally NTFY_TOPIC, DASHBOARD_URL (the dashboard's Tailscale
// address, so a push opens the requests page), SEND_TOKEN (the share sheet's; without it /api/send refuses every
// send) and TURNSTILE_SECRET. The suite puts NTFY_TOPIC, DASHBOARD_URL and SEND_TOKEN from .env after every deploy
// (site/deploy.py).
const ALLOWED = /^(image\/(jpeg|png|gif)|video\/mp4)$/;
const PUBLIC_PREFIX = "convention-social/";
const PRIVATE_PREFIX = "private/";
const FIELDS = { name: 120, email: 200, phone: 40, organization: 160, event_name: 200, event_kind: 20, start_date: 10,
                 end_date: 10, city: 120, venue: 200, attendance: 40, message: 4000 };
const COVERAGE = ["backstage", "green_room", "breakouts", "evening_events", "dinners", "portraits", "exhibition_hall",
                  "on_site_delivery", "stage"];      // portraits and headshots are one thing; so are exhibition halls, vendors and booths (Chris, 2026-10-12)
const PER_HOUR = 5;
const OPT_OUT_TOKEN = /^[a-f0-9]{32}$/;
const OPT_OUTS_PER_HOUR = 20;     // per address; mail providers send one-click opt-outs from shared addresses
const HEARTBEAT_KEY = `${PRIVATE_PREFIX}heartbeat.json`;
const ALERTED_KEY = `${PRIVATE_PREFIX}heartbeat-alerted.json`;
const QUIET_MS = 2 * 3600e3;      // the Mini checks in hourly; two hours of silence is the alarm
const SENDS_PREFIX = `${PRIVATE_PREFIX}sends/`;
const SEND_LOG_KEY = `${PRIVATE_PREFIX}send-log.json`;
const SEND_MAX_BYTES = 40 * 1024 * 1024;     // the Mini's own limit (agents/phone.py MAX_BYTES)
const SEND_NOTE_MAX = 140;                   // agents/phone.py NOTE_MAX
const SENDS_PER_HOUR = 20;
const SENDS_WAITING_MAX = 30;                // the Mini is off or not pulling: the bucket never fills
const SEND_ID = /^\d{13}-[0-9a-f]{16}$/;
const TEAM_KEY = `${PRIVATE_PREFIX}team.json`;
const SESSIONS_PREFIX = `${PRIVATE_PREFIX}team-sessions/`;
const JOINS_USED_PREFIX = `${PRIVATE_PREFIX}team-joins-used/`;
const SESSION_COOKIE = "ec_send";
const HEX64 = /^[0-9a-f]{64}$/;
const TOKEN_SHAPE = /^[A-Za-z0-9_-]{40,64}$/;      // a team token as the Mini makes it (token_urlsafe(32)); nothing else is looked up

const authed = (request, env) =>
  Boolean(env.UPLOAD_TOKEN) && (request.headers.get("authorization") || "") === `Bearer ${env.UPLOAD_TOKEN}`;

async function readForm(request) {
  const type = (request.headers.get("content-type") || "").split(";")[0].trim();
  if (type === "application/json") return await request.json();
  const form = await request.formData();
  const out = {};
  for (const [k, v] of form.entries()) {
    if (k === "coverage") (out.coverage ||= []).push(String(v));
    else out[k] = String(v);
  }
  return out;
}

async function turnstileOk(env, token, ip) {
  if (!env.TURNSTILE_SECRET) return true;            // not set up yet: the honeypot and the rate limit still apply
  if (!token) return false;
  const body = new FormData();
  body.append("secret", env.TURNSTILE_SECRET);
  body.append("response", token);
  if (ip) body.append("remoteip", ip);
  const r = await fetch("https://challenges.cloudflare.com/turnstile/v0/siteverify", { method: "POST", body });
  return Boolean((await r.json()).success);
}

const done = (request, status, payload) => {
  const wantsJson = (request.headers.get("accept") || "").includes("application/json");
  if (wantsJson) return Response.json(payload, { status });
  const to = status < 300 ? "/thanks/" : `/book/?error=${encodeURIComponent(payload.error || "error")}`;
  return Response.redirect(new URL(to, request.url).toString(), 303);
};

async function quote(request, env) {
  let data;
  try { data = await readForm(request); } catch { return done(request, 400, { error: "unreadable" }); }
  if ((data.website || "").trim()) return done(request, 200, { ok: true });       // the honeypot: quietly dropped
  const ip = request.headers.get("cf-connecting-ip") || "";
  if (!(await turnstileOk(env, data["cf-turnstile-response"], ip))) return done(request, 400, { error: "check" });
  const rec = {};
  for (const [k, max] of Object.entries(FIELDS)) rec[k] = String(data[k] || "").trim().slice(0, max);
  if (!rec.name || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(rec.email)) return done(request, 400, { error: "missing" });
  for (const k of ["start_date", "end_date"]) if (rec[k] && !/^\d{4}-\d{2}-\d{2}$/.test(rec[k])) rec[k] = "";
  rec.coverage = (Array.isArray(data.coverage) ? data.coverage : [data.coverage]).filter((c) => COVERAGE.includes(c));
  const now = new Date();
  const hourAgo = new Date(now.getTime() - 3600e3).toISOString();
  const recent = await env.DB.prepare("SELECT COUNT(*) AS n FROM quote_requests WHERE ip = ? AND received_at > ?")
    .bind(ip, hourAgo).first();
  if ((recent?.n || 0) >= PER_HOUR) return done(request, 429, { error: "busy" });
  const id = crypto.randomUUID();
  await env.DB.prepare("INSERT INTO quote_requests (id, received_at, ip, body) VALUES (?, ?, ?, ?)")
    .bind(id, now.toISOString(), ip, JSON.stringify(rec)).run();
  if (env.NTFY_TOPIC) {
    // no name, email or phone in the push: ntfy topics are not private
    const what = [rec.event_name || "an event", rec.start_date].filter(Boolean).join(", ");
    const headers = { Title: "Quote request", Priority: "high" };
    if (env.DASHBOARD_URL) headers.Click = `${env.DASHBOARD_URL}/inquiries`;      // 2026-10-13: the ping ends where he can act
    await fetch(`https://ntfy.sh/${env.NTFY_TOPIC}`, { method: "POST", body: `New quote request: ${what}`, headers }).catch(() => {});
  }
  return done(request, 200, { ok: true, id });
}

async function inquiries(request, env, url) {
  if (!authed(request, env)) return new Response("forbidden", { status: 403 });
  if (request.method === "GET") {
    const { results } = await env.DB.prepare("SELECT id, received_at, body FROM quote_requests ORDER BY received_at LIMIT 200").all();
    return Response.json({ inquiries: results.map((r) => ({ id: r.id, received_at: r.received_at, ...JSON.parse(r.body) })) });
  }
  if (request.method === "POST" && url.pathname === "/api/inquiries/ack") {
    const ids = ((await request.json()).ids || []).filter((x) => typeof x === "string").slice(0, 200);
    for (const id of ids) await env.DB.prepare("DELETE FROM quote_requests WHERE id = ?").bind(id).run();
    return Response.json({ ok: true, deleted: ids.length });
  }
  return new Response("method not allowed", { status: 405 });
}

async function availability(request, env) {
  if (request.method === "GET") {
    const today = new Date().toISOString().slice(0, 10);
    const { results } = await env.DB.prepare("SELECT day FROM booked_days WHERE day >= ? ORDER BY day").bind(today).all();
    return Response.json({ booked: results.map((r) => r.day) }, { headers: { "cache-control": "public, max-age=300" } });
  }
  if (request.method === "PUT") {
    if (!authed(request, env)) return new Response("forbidden", { status: 403 });
    const days = ((await request.json()).booked || []).filter((d) => /^\d{4}-\d{2}-\d{2}$/.test(d)).slice(0, 1000);
    await env.DB.prepare("DELETE FROM booked_days").run();
    for (const d of days) await env.DB.prepare("INSERT OR IGNORE INTO booked_days (day) VALUES (?)").bind(d).run();
    return Response.json({ ok: true, booked: days.length });
  }
  return new Response("method not allowed", { status: 405 });
}

const escapeHtml = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

function optOutPage(title, inner, status = 200) {
  const html = `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">` +
    `<meta name="robots" content="noindex"><title>${escapeHtml(title)}</title>` +
    `<style>body{margin:0;font:17px/1.5 -apple-system,BlinkMacSystemFont,"Helvetica Neue",Arial,sans-serif;background:#f4f4f2;color:#17171a}` +
    `main{max-width:520px;margin:12vh auto;padding:24px;background:#fff;border:1px solid #e2e1dc;border-radius:12px}` +
    `button{font:inherit;font-weight:600;padding:12px 18px;border:0;border-radius:10px;background:#1f4fd1;color:#fff;cursor:pointer}</style>` +
    `</head><body><main><h1 style="font-size:22px;margin-top:0">${escapeHtml(title)}</h1>${inner}</main></body></html>`;
  return new Response(html, { status, headers: { "content-type": "text/html; charset=utf-8", "cache-control": "no-store" } });
}

async function readToken(request, url) {
  const fromQuery = url.searchParams.get("t") || "";
  if (fromQuery) return fromQuery;
  try {
    const type = (request.headers.get("content-type") || "").split(";")[0].trim();
    if (type === "application/json") return String((await request.json()).t || "");
    const form = await request.formData();
    return String(form.get("t") || "");
  } catch { return ""; }
}

function unsubscribePage(url) {
  const t = url.searchParams.get("t") || "";
  if (!OPT_OUT_TOKEN.test(t)) {
    return optOutPage("Unsubscribe", "<p>This link is not complete. You can reply STOP to the email instead.</p>", 400);
  }
  return optOutPage("Unsubscribe", `<p>Stop getting email about event photography at this address?</p>` +
    `<form method="post" action="/api/unsubscribe"><input type="hidden" name="t" value="${escapeHtml(t)}">` +
    `<button type="submit">Unsubscribe</button></form>`);
}

async function optOut(request, env, url) {
  const wantsJson = (request.headers.get("accept") || "").includes("application/json");
  const reply = (status, payload, text) => (wantsJson ? Response.json(payload, { status }) : optOutPage("Unsubscribe", `<p>${text}</p>`, status));
  const t = await readToken(request, url);
  if (!OPT_OUT_TOKEN.test(t)) return reply(400, { error: "token" }, "This link is not complete. You can reply STOP to the email instead.");
  const ip = request.headers.get("cf-connecting-ip") || "";
  const now = new Date();
  const hourAgo = new Date(now.getTime() - 3600e3).toISOString();
  const recent = await env.DB.prepare("SELECT COUNT(*) AS n FROM unsubscribes WHERE ip = ? AND received_at > ?").bind(ip, hourAgo).first();
  if ((recent?.n || 0) >= OPT_OUTS_PER_HOUR) {
    return reply(429, { error: "busy" }, "Too many requests from here just now. Please try again in an hour, or reply STOP to the email.");
  }
  await env.DB.prepare("INSERT OR IGNORE INTO unsubscribes (token, received_at, ip) VALUES (?, ?, ?)").bind(t, now.toISOString(), ip).run();
  return reply(200, { ok: true }, "You are unsubscribed. You will not get another email from us at this address.");
}

async function unsubscribes(request, env, url) {
  if (!authed(request, env)) return new Response("forbidden", { status: 403 });
  if (request.method === "GET" && url.pathname === "/api/unsubscribes") {
    const { results } = await env.DB.prepare("SELECT token, received_at FROM unsubscribes ORDER BY received_at LIMIT 500").all();
    return Response.json({ unsubscribes: results.map((r) => ({ token: r.token, received_at: r.received_at })) });
  }
  if (request.method === "POST" && url.pathname === "/api/unsubscribes/ack") {
    const tokens = ((await request.json()).tokens || []).filter((x) => typeof x === "string" && OPT_OUT_TOKEN.test(x)).slice(0, 500);
    for (const t of tokens) await env.DB.prepare("DELETE FROM unsubscribes WHERE token = ?").bind(t).run();
    return Response.json({ ok: true, deleted: tokens.length });
  }
  return new Response("method not allowed", { status: 405 });
}

async function readJson(env, key) {
  const obj = await env.MEDIA.get(key);
  if (!obj) return null;
  try { return JSON.parse(await obj.text()); } catch { return null; }
}

async function push(env, title, body, priority) {
  if (!env.NTFY_TOPIC) return false;
  const headers = { Title: title, Priority: priority };
  if (env.DASHBOARD_URL) headers.Click = env.DASHBOARD_URL;
  await fetch(`https://ntfy.sh/${env.NTFY_TOPIC}`, { method: "POST", body, headers }).catch(() => {});
  return true;
}

async function heartbeat(request, env, url) {
  if (!authed(request, env)) return new Response("forbidden", { status: 403 });
  if (request.method !== "POST") return new Response("method not allowed", { status: 405 });
  if (url.pathname === "/api/heartbeat/test") {
    const sent = await push(env, "Event Caliber: the Mini is silent (test)",
      "This is the outside watch's test ping. If the Mini stops checking in for two hours, this is what you get. (test)", "urgent");
    return Response.json({ ok: true, sent });
  }
  const at = new Date(Date.now()).toISOString();
  await env.MEDIA.put(HEARTBEAT_KEY, JSON.stringify({ at }), { httpMetadata: { contentType: "application/json" } });
  return Response.json({ ok: true, at });
}

async function watch(env) {
  const beat = await readJson(env, HEARTBEAT_KEY);
  if (!beat || !beat.at) return { state: "never" };            // never set up: silence is not news
  const alerted = await readJson(env, ALERTED_KEY);
  if (Date.now() - Date.parse(beat.at) > QUIET_MS) {
    if (alerted) return { state: "silent", pushed: false };
    await push(env, "Event Caliber: the Mini is silent",
      `The Mini has not checked in since ${beat.at}. Nothing posts, drafts or answers until it is back. Tap for the dashboard.`, "urgent");
    await env.MEDIA.put(ALERTED_KEY, JSON.stringify({ at: new Date(Date.now()).toISOString(), since: beat.at }),
      { httpMetadata: { contentType: "application/json" } });
    return { state: "silent", pushed: true };
  }
  if (alerted) {
    await push(env, "Event Caliber: the Mini is back", `The Mini is back: it checked in at ${beat.at}.`, "default");
    await env.MEDIA.delete(ALERTED_KEY);
    return { state: "back", pushed: true };
  }
  return { state: "fine" };
}

// ------------------------------------------------------------------ Post to Event Caliber (2026-10-15)

async function sameSecret(given, expected) {
  // compared as SHA-256 digests, byte by byte to the end: no early exit tells a guesser how much was right
  const enc = new TextEncoder();
  const [a, b] = await Promise.all([crypto.subtle.digest("SHA-256", enc.encode(given)), crypto.subtle.digest("SHA-256", enc.encode(expected))]);
  const x = new Uint8Array(a), y = new Uint8Array(b);
  let diff = 0;
  for (let i = 0; i < x.length; i++) diff |= x[i] ^ y[i];
  return diff === 0;
}

function photoType(head) {
  // by the file's own bytes, never the name or the type the phone gave it
  if (head[0] === 0xff && head[1] === 0xd8 && head[2] === 0xff) return "image/jpeg";
  if ([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a].every((b, i) => head[i] === b)) return "image/png";
  const box = String.fromCharCode(...head.slice(4, 12));
  if (/^ftyp(heic|heix|heim|heis|hevc|hevx|mif1|msf1)$/.test(box)) return "image/heic";
  return "";
}

const said = (status, text) => new Response(text, { status, headers: { "content-type": "text/plain; charset=utf-8", "cache-control": "no-store" } });

async function sha256hex(text) {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

const cookieOf = (request, name) => {
  for (const part of (request.headers.get("cookie") || "").split(";")) {
    const [k, ...v] = part.trim().split("=");
    if (k === name) return v.join("=");
  }
  return "";
};

async function memberOf(env, check) {
  const team = await readJson(env, TEAM_KEY);
  return ((team && team.members) || []).find((m) => m.active === true && check(m)) || null;
}

async function sessionMember(request, env) {
  // the upload page's cookie: a session of its own, mapped to a photographer who is still on
  const session = cookieOf(request, SESSION_COOKIE);
  if (!TOKEN_SHAPE.test(session)) return null;
  const rec = await readJson(env, `${SESSIONS_PREFIX}${await sha256hex(session)}`);
  return rec ? memberOf(env, (m) => m.id === rec.member_id) : null;
}

async function senderOf(request, env, url) {
  // "chris" (his SEND_TOKEN), "m<number>" (a photographer on the team), or null. A cookie counts only from the site's
  // own page: the request must say it came from this origin (a page elsewhere cannot send with it).
  const auth = request.headers.get("authorization") || "";
  if (auth.startsWith("Bearer ")) {
    const given = auth.slice(7);
    if (env.SEND_TOKEN && (await sameSecret(given, env.SEND_TOKEN))) return "chris";
    if (!TOKEN_SHAPE.test(given)) return null;
    const hash = await sha256hex(given);
    const m = await memberOf(env, (x) => x.token_sha256 === hash);
    return m ? `m${m.id}` : null;
  }
  if (cookieOf(request, SESSION_COOKIE)) {
    if (request.headers.get("origin") !== url.origin) return null;
    const m = await sessionMember(request, env);
    return m ? `m${m.id}` : null;
  }
  return null;
}

async function sendPhoto(request, env, url) {
  if (request.method !== "POST") return said(405, "Not received: send the photo from the share sheet.");
  const who = await senderOf(request, env, url);
  if (!who && !env.SEND_TOKEN && !(await memberOf(env, () => true))) {
    return said(503, "Not received: sending from the phone is not set up on the site yet. Make a send token on the Keys page; the site takes it within about twenty minutes.");
  }
  if (!who) {
    return said(403, "Not received: the site does not know this token. A new one takes about twenty minutes to reach the site; if yours is older, make a new one on the Keys page and put it in the Shortcut.");
  }
  if (Number(request.headers.get("content-length") || 0) > SEND_MAX_BYTES + 1024 * 1024) {
    return said(413, "Not received: the photo is over 40 MB.");
  }
  let form;
  try { form = await request.formData(); } catch { return said(400, "Not received: no photo came with it. In the Shortcut, the request body is a Form."); }
  const file = form.get("photo");
  if (!file || typeof file === "string") return said(400, "Not received: no photo came with it. In the Shortcut, the photo goes in a File field called photo.");
  if (file.size > SEND_MAX_BYTES) return said(413, "Not received: the photo is over 40 MB.");
  const type = photoType(new Uint8Array(await file.slice(0, 16).arrayBuffer()));
  if (!type) return said(415, "Not received: not a JPEG, PNG or HEIC photo.");
  const listed = await env.MEDIA.list({ prefix: SENDS_PREFIX, limit: SENDS_WAITING_MAX + 1 });
  if (listed.objects.length >= SENDS_WAITING_MAX) {
    return said(503, `Not received: ${SENDS_WAITING_MAX} photos are already waiting and the Mini has not picked them up. Check the Mini.`);
  }
  const now = Date.now();
  const logKey = who === "chris" ? SEND_LOG_KEY : `${PRIVATE_PREFIX}send-log-${who}.json`;      // each sender's own hour
  const log = ((await readJson(env, logKey)) || []).filter((t) => typeof t === "number" && now - t < 3600e3);
  if (log.length >= SENDS_PER_HOUR) return said(429, `Not received: ${SENDS_PER_HOUR} photos an hour is the limit. Try again in a while.`);
  const line = String(form.get("note") || "").split(/\s+/).filter(Boolean).join(" ").slice(0, SEND_NOTE_MAX);
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes.subarray(0, 8));
  const id = `${now}-${[...bytes.subarray(0, 8)].map((b) => b.toString(16).padStart(2, "0")).join("")}`;
  await env.MEDIA.put(`${SENDS_PREFIX}${id}`, file, { httpMetadata: { contentType: type },
    customMetadata: { note: line, type, sender: who, received_at: new Date(now).toISOString() } });
  await env.MEDIA.put(logKey, JSON.stringify([...log, now]), { httpMetadata: { contentType: "application/json" } });
  return said(200, who === "chris" ? "Received. In a few minutes your phone gets a ping saying whether it passed and when it goes out."
                                   : "Received. Chris or Nic approves it before it goes out.");
}

async function team(request, env) {
  if (!authed(request, env)) return new Response("forbidden", { status: 403 });
  if (request.method !== "PUT") return new Response("method not allowed", { status: 405 });
  let body;
  try { body = await request.json(); } catch { return new Response("bad team", { status: 400 }); }
  const members = Array.isArray(body.members) ? body.members : [];
  const joins = Array.isArray(body.joins) ? body.joins : [];
  const okMember = (m) => Number.isInteger(m.id) && HEX64.test(m.token_sha256 || "") && typeof m.active === "boolean";
  const okJoin = (j) => HEX64.test(j.code_sha256 || "") && Number.isInteger(j.member_id) && !Number.isNaN(Date.parse(j.expires_at));
  if (!members.every(okMember) || !joins.every(okJoin)) return new Response("bad team", { status: 400 });
  const clean = { members: members.map(({ id, token_sha256, active }) => ({ id, token_sha256, active })),
                  joins: joins.map(({ code_sha256, member_id, expires_at }) => ({ code_sha256, member_id, expires_at })) };
  await env.MEDIA.put(TEAM_KEY, JSON.stringify(clean), { httpMetadata: { contentType: "application/json" } });
  return Response.json({ ok: true, members: clean.members.length, joins: clean.joins.length });
}

function teamPage(title, inner, status = 200, extra = {}) {
  const html = `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">` +
    `<meta name="robots" content="noindex"><meta name="theme-color" content="#f4f4f2"><title>${escapeHtml(title)}</title>` +
    `<link rel="manifest" href="/upload/manifest.webmanifest"><link rel="icon" href="/assets/mark.svg" type="image/svg+xml">` +
    `<style>body{margin:0;font:17px/1.5 -apple-system,BlinkMacSystemFont,"Helvetica Neue",Arial,sans-serif;background:#f4f4f2;color:#17171a}` +
    `main{max-width:480px;margin:0 auto;padding:28px 20px}h1{font-size:24px;margin:8px 0 12px}p{color:#4a4a50}` +
    `label{display:block;margin:18px 0 6px;font-weight:600}input[type=text]{width:100%;box-sizing:border-box;font:inherit;padding:12px;` +
    `border-radius:10px;border:1px solid #d6d5d0;background:#fff;color:#17171a}input[type=file]{font:inherit}` +
    `button{font:inherit;font-weight:700;width:100%;margin-top:22px;padding:16px;border:0;border-radius:12px;background:#0a0a0b;color:#fff}` +
    `#said{margin-top:18px;padding:14px;border-radius:10px;background:#fff;border:1px solid #e2e1dc;display:none}.mark{width:44px;height:44px}</style>` +
    `</head><body><main><img class="mark" src="/assets/mark.svg" alt=""><h1>${escapeHtml(title)}</h1>${inner}</main></body></html>`;
  return new Response(html, { status, headers: { "content-type": "text/html; charset=utf-8", "cache-control": "no-store",
    "referrer-policy": "no-referrer", "x-frame-options": "DENY", ...extra } });
}

const GET_IN = "<p>Open the link you were sent on this phone, then tap the button on it. The link works once.</p>";

async function joinPage(request, env, url) {
  if (request.method === "GET" && url.pathname.startsWith("/join/")) {
    const code = url.pathname.slice("/join/".length);
    if (!TOKEN_SHAPE.test(code) && !/^[A-Za-z0-9_-]{24,64}$/.test(code)) return teamPage("Send photos to Event Caliber", GET_IN, 400);
    return teamPage("Send photos to Event Caliber", `<p>This sets up this phone to send your photos to Event Caliber. Chris or Nic ` +
      `approves each one before it goes out. Tap once, then save the page to your home screen.</p>` +
      `<form method="post" action="/join"><input type="hidden" name="code" value="${escapeHtml(code)}">` +
      `<button type="submit">Set up this phone</button></form>`);
  }
  if (request.method !== "POST" || url.pathname !== "/join") return new Response("method not allowed", { status: 405 });
  if (request.headers.get("origin") !== url.origin) return teamPage("Send photos to Event Caliber", GET_IN, 403);
  let code = "";
  try { code = String((await request.formData()).get("code") || ""); } catch { code = ""; }
  const hash = await sha256hex(code);
  const teamList = await readJson(env, TEAM_KEY);
  const join = ((teamList && teamList.joins) || []).find((j) => j.code_sha256 === hash);
  const m = join && (await memberOf(env, (x) => x.id === join.member_id));
  const used = join && (await env.MEDIA.get(`${JOINS_USED_PREFIX}${hash}`));
  if (!join || !m || used || Date.parse(join.expires_at) < Date.now()) {
    return teamPage("Send photos to Event Caliber", "<p>This link has been used or has expired. Ask Chris or Nic for a new one.</p>", 403);
  }
  const at = new Date(Date.now()).toISOString();
  await env.MEDIA.put(`${JOINS_USED_PREFIX}${hash}`, JSON.stringify({ at }), { httpMetadata: { contentType: "application/json" } });
  const raw = new Uint8Array(32);
  crypto.getRandomValues(raw);
  const session = btoa(String.fromCharCode(...raw)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  await env.MEDIA.put(`${SESSIONS_PREFIX}${await sha256hex(session)}`, JSON.stringify({ member_id: m.id, at }),
    { httpMetadata: { contentType: "application/json" } });
  return new Response(null, { status: 303, headers: { location: "/upload", "cache-control": "no-store", "referrer-policy": "no-referrer",
    "set-cookie": `${SESSION_COOKIE}=${session}; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age=31536000` } });
}

const UPLOAD_SCRIPT = `<script>document.querySelector("form").addEventListener("submit",async(e)=>{e.preventDefault();` +
  `const b=e.target.querySelector("button"),s=document.getElementById("said");b.disabled=true;b.textContent="Sending";` +
  `try{const r=await fetch("/api/send",{method:"POST",body:new FormData(e.target),credentials:"same-origin"});s.textContent=await r.text();` +
  `if(r.ok)e.target.reset();}catch(x){s.textContent="Not sent: no connection. Try again in a moment.";}` +
  `s.style.display="block";b.disabled=false;b.textContent="Send";});</script>`;

async function uploadPage(request, env, url) {
  if (url.pathname === "/upload/manifest.webmanifest") {
    return Response.json({ name: "Event Caliber: send a photo", short_name: "Send a photo", start_url: "/upload", scope: "/upload",
      display: "standalone", background_color: "#f4f4f2", theme_color: "#f4f4f2",
      icons: [{ src: "/assets/mark.svg", sizes: "any", type: "image/svg+xml" }] }, { headers: { "cache-control": "public, max-age=3600" } });
  }
  if (!(await sessionMember(request, env))) return teamPage("Send photos to Event Caliber", GET_IN);
  return teamPage("Send a photo", `<p>One photo from the event you are shooting, and a line about it if you like (what the room was; ` +
    `never a name or which event). Chris or Nic approves it before it goes out.</p><form><label>The photo</label>` +
    `<input type="file" name="photo" accept="image/*" required><label>A line about it (optional)</label>` +
    `<input type="text" name="note" maxlength="140" autocomplete="off"><button type="submit">Send</button></form><div id="said"></div>` +
    UPLOAD_SCRIPT);
}

async function sends(request, env, url) {
  if (!authed(request, env)) return new Response("forbidden", { status: 403 });
  if (request.method === "GET" && url.pathname === "/api/sends") {
    const listed = await env.MEDIA.list({ prefix: SENDS_PREFIX, limit: 100, include: ["customMetadata"] });
    return Response.json({ sends: listed.objects.map((o) => ({ id: o.key.slice(SENDS_PREFIX.length), size: o.size,
      note: o.customMetadata?.note || "", type: o.customMetadata?.type || "", sender: o.customMetadata?.sender || "chris",
      received_at: o.customMetadata?.received_at || "" })) });
  }
  if (request.method === "POST" && url.pathname === "/api/sends/ack") {
    const ids = ((await request.json()).ids || []).filter((x) => typeof x === "string" && SEND_ID.test(x)).slice(0, 100);
    for (const id of ids) await env.MEDIA.delete(`${SENDS_PREFIX}${id}`);
    return Response.json({ ok: true, deleted: ids.length });
  }
  if (request.method === "GET") {
    let id;
    try { id = decodeURIComponent(url.pathname.slice("/api/sends/".length)); } catch { id = ""; }
    if (!SEND_ID.test(id)) return new Response("bad id", { status: 400 });
    const obj = await env.MEDIA.get(`${SENDS_PREFIX}${id}`);
    if (!obj) return new Response("not found", { status: 404 });
    const headers = new Headers({ "cache-control": "no-store" });
    obj.writeHttpMetadata(headers);
    return new Response(obj.body, { headers });
  }
  return new Response("method not allowed", { status: 405 });
}

async function media(request, env, url) {
  let key;
  try { key = decodeURIComponent(url.pathname.slice(3)); } catch { return new Response("bad key", { status: 400 }); }
  if (!key || key.includes("..") || key.startsWith("/") || key.length > 512) return new Response("bad key", { status: 400 });
  if (request.method === "GET" || request.method === "HEAD") {
    if (!key.startsWith(PUBLIC_PREFIX)) return new Response("not found", { status: 404 });
    const obj = await env.MEDIA.get(key);
    if (!obj) return new Response("not found", { status: 404 });
    const headers = new Headers();
    obj.writeHttpMetadata(headers);
    headers.set("etag", obj.httpEtag);
    headers.set("cache-control", "public, max-age=300");
    return new Response(request.method === "HEAD" ? null : obj.body, { headers });
  }
  if (request.method === "PUT") {
    if (!authed(request, env)) return new Response("forbidden", { status: 403 });
    const type = (request.headers.get("content-type") || "").split(";")[0].trim();
    const isPrivate = key.startsWith(PRIVATE_PREFIX);
    if (!isPrivate && !key.startsWith(PUBLIC_PREFIX)) return new Response("bad key", { status: 400 });
    if (isPrivate ? type !== "application/gzip" : !ALLOWED.test(type)) return new Response("unsupported type", { status: 415 });
    await env.MEDIA.put(key, request.body, { httpMetadata: { contentType: type } });
    return Response.json({ ok: true, key });
  }
  return new Response("method not allowed", { status: 405 });
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.hostname.startsWith("www.")) {
      // one address for search engines (2026-10-14): www. is the same site, so it goes to the apex for good
      url.hostname = url.hostname.slice(4);
      return Response.redirect(url.toString(), 301);
    }
    if (url.pathname.startsWith("/m/")) return media(request, env, url);
    if (url.pathname === "/api/quote") {
      return request.method === "POST" ? quote(request, env) : new Response("method not allowed", { status: 405 });
    }
    if (url.pathname === "/api/inquiries" || url.pathname === "/api/inquiries/ack") return inquiries(request, env, url);
    if (url.pathname === "/api/availability") return availability(request, env);
    if (url.pathname === "/unsubscribe" || url.pathname === "/unsubscribe/") {
      if (request.method === "GET" || request.method === "HEAD") return unsubscribePage(url);
      return request.method === "POST" ? optOut(request, env, url) : new Response("method not allowed", { status: 405 });
    }
    if (url.pathname === "/api/unsubscribe") {
      return request.method === "POST" ? optOut(request, env, url) : new Response("method not allowed", { status: 405 });
    }
    if (url.pathname === "/api/unsubscribes" || url.pathname === "/api/unsubscribes/ack") return unsubscribes(request, env, url);
    if (url.pathname === "/api/heartbeat" || url.pathname === "/api/heartbeat/test") return heartbeat(request, env, url);
    if (url.pathname === "/api/send") return sendPhoto(request, env, url);
    if (url.pathname === "/api/team") return team(request, env);
    if (url.pathname === "/join" || url.pathname.startsWith("/join/")) return joinPage(request, env, url);
    if (url.pathname === "/upload" || url.pathname === "/upload/" || url.pathname === "/upload/manifest.webmanifest") return uploadPage(request, env, url);
    if (url.pathname === "/api/sends" || url.pathname.startsWith("/api/sends/")) return sends(request, env, url);
    if (url.pathname.startsWith("/api/")) return new Response("not found", { status: 404 });
    return env.ASSETS ? env.ASSETS.fetch(request) : new Response("not found", { status: 404 });
  },
  async scheduled(controller, env, ctx) {
    await watch(env);
  },
};
