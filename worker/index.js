// Image hosting for the company's posts: /m/<key> on the company's own domain, backed by its own bucket (binding MEDIA).
// GET/HEAD /m/<key> is public ONLY under convention-social/ (Buffer, Instagram, Facebook and Pinterest fetch post images here).
// PUT /m/<key> stores a file and needs the upload token the Mac mini holds (secret UPLOAD_TOKEN, `wrangler secret put UPLOAD_TOKEN`).
// Keys under private/ (the nightly database backup) can be written with the token and are never served.
// Every other path is 404: this Worker serves nothing else.
const ALLOWED = /^(image\/(jpeg|png|gif)|video\/mp4)$/;
const PUBLIC_PREFIX = "convention-social/";
const PRIVATE_PREFIX = "private/";

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (!url.pathname.startsWith("/m/")) return new Response("not found", { status: 404 });
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
      const auth = request.headers.get("authorization") || "";
      if (!env.UPLOAD_TOKEN || auth !== `Bearer ${env.UPLOAD_TOKEN}`) return new Response("forbidden", { status: 403 });
      const type = (request.headers.get("content-type") || "").split(";")[0].trim();
      const isPrivate = key.startsWith(PRIVATE_PREFIX);
      if (!isPrivate && !key.startsWith(PUBLIC_PREFIX)) return new Response("bad key", { status: 400 });
      if (isPrivate ? type !== "application/gzip" : !ALLOWED.test(type)) return new Response("unsupported type", { status: 415 });
      await env.MEDIA.put(key, request.body, { httpMetadata: { contentType: type } });
      return Response.json({ ok: true, key });
    }
    return new Response("method not allowed", { status: 405 });
  },
};
