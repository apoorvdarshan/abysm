// HSTS for this subdomain only: no includeSubDomains and no preload, so the
// rest of apoorvdarshan.com is unaffected.
const HSTS = "max-age=31536000";

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    // Cloudflare also serves the custom domain over plain HTTP; send it to HTTPS.
    if (url.protocol === "http:") {
      url.protocol = "https:";
      return Response.redirect(url.toString(), 301);
    }

    const response = await env.ASSETS.fetch(request);
    const headers = new Headers(response.headers);
    headers.set("Strict-Transport-Security", HSTS);
    if (url.pathname.startsWith("/assets/") || url.pathname.startsWith("/fonts/")) {
      headers.set("Cache-Control", "public, max-age=86400, stale-while-revalidate=604800");
    }
    return new Response(response.body, {
      status: response.status,
      statusText: response.statusText,
      headers,
    });
  },
};
