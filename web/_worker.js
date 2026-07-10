const canonicalHost = "abysm.apoorvdarshan.com";

function isCloudflarePagesHost(hostname) {
  return hostname === "abysm.pages.dev" || hostname.endsWith(".abysm.pages.dev");
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (isCloudflarePagesHost(url.hostname)) {
      url.protocol = "https:";
      url.hostname = canonicalHost;
      url.port = "";
      return Response.redirect(url.toString(), 301);
    }

    const response = await env.ASSETS.fetch(request);
    if (url.pathname.startsWith("/assets/") || url.pathname.startsWith("/fonts/")) {
      const headers = new Headers(response.headers);
      headers.set("Cache-Control", "public, max-age=31536000, immutable");
      return new Response(response.body, {
        status: response.status,
        statusText: response.statusText,
        headers,
      });
    }

    return response;
  },
};
