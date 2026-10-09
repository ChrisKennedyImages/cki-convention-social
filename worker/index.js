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
//
// Secrets (wrangler secret put): UPLOAD_TOKEN, and optionally NTFY_TOPIC and TURNSTILE_SECRET.
const ALLOWED = /^(image\/(jpeg|png|gif)|video\/mp4)$/;
const PUBLIC_PREFIX = "convention-social/";
const PRIVATE_PREFIX = "private/";
const FIELDS = { name: 120, email: 200, phone: 40, organization: 160, event_name: 200, event_kind: 20, start_date: 10,
                 end_date: 10, city: 120, venue: 200, attendance: 40, message: 4000 };
const COVERAGE = ["backstage", "green_room", "breakouts", "evening_events", "dinners", "portraits", "exhibition_hall",
                  "vendors", "on_site_delivery", "cosplay", "stage", "headshots"];
const PER_HOUR = 5;

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
    await fetch(`https://ntfy.sh/${env.NTFY_TOPIC}`, { method: "POST", body: `New quote request: ${what}`,
      headers: { Title: "Quote request", Priority: "high" } }).catch(() => {});
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
    if (url.pathname.startsWith("/m/")) return media(request, env, url);
    if (url.pathname === "/api/quote") {
      return request.method === "POST" ? quote(request, env) : new Response("method not allowed", { status: 405 });
    }
    if (url.pathname === "/api/inquiries" || url.pathname === "/api/inquiries/ack") return inquiries(request, env, url);
    if (url.pathname === "/api/availability") return availability(request, env);
    if (url.pathname.startsWith("/api/")) return new Response("not found", { status: 404 });
    return env.ASSETS ? env.ASSETS.fetch(request) : new Response("not found", { status: 404 });
  },
};
