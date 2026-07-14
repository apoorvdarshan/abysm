export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const response = await env.ASSETS.fetch(request);
    if (url.pathname.startsWith("/assets/") || url.pathname.startsWith("/fonts/")) {
      const headers = new Headers(response.headers);
      headers.set("Cache-Control", "public, max-age=86400, stale-while-revalidate=604800");
      return new Response(response.body, {
        status: response.status,
        statusText: response.statusText,
        headers,
      });
    }

    return response;
  },
};
