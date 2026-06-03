import json

from django.http import HttpResponse
from django.views.decorators.http import require_GET


@require_GET
def manifest_webmanifest(_request):
    manifest = {
        "name": "Stafforyx HR",
        "short_name": "Stafforyx",
        "start_url": "/",
        "scope": "/",
        "display": "standalone",
        "background_color": "#0f172a",
        "theme_color": "#0f172a",
        "orientation": "portrait-primary",
        "icons": [
            {
                "src": "/static/images/pwa/icon-192.png",
                "sizes": "192x192",
                "type": "image/png",
            },
            {
                "src": "/static/images/pwa/icon-512.png",
                "sizes": "512x512",
                "type": "image/png",
            },
            {
                "src": "/static/images/pwa/apple-touch-icon.png",
                "sizes": "180x180",
                "type": "image/png",
            },
        ],
    }
    return HttpResponse(
        json.dumps(manifest, separators=(",", ":")),
        content_type="application/manifest+json",
    )


@require_GET
def service_worker(_request):
    service_worker_js = """
const CACHE_NAME = "stafforyx-pwa-v2";
const OFFLINE_URL = "/static/offline.html";
const PRECACHE_URLS = [
  OFFLINE_URL,
  "/static/images/pwa/icon-192.png",
  "/static/images/pwa/icon-512.png",
  "/static/images/pwa/apple-touch-icon.png"
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(PRECACHE_URLS))
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys
          .filter((key) => key !== CACHE_NAME)
          .map((key) => caches.delete(key))
      )
    )
  );
  self.clients.claim();
});

function isSameOriginStaticAsset(requestUrl) {
  const url = new URL(requestUrl);
  if (url.origin !== self.location.origin) return false;
  return url.pathname.startsWith("/static/");
}

self.addEventListener("fetch", (event) => {
  const { request } = event;

  if (request.method !== "GET") return;

  if (request.mode === "navigate") {
    event.respondWith(
      fetch(request).catch(() => caches.match(OFFLINE_URL))
    );
    return;
  }

  if (isSameOriginStaticAsset(request.url)) {
    event.respondWith(
      caches.match(request).then((cached) => {
        if (cached) return cached;
        return fetch(request)
          .then((response) => {
            const cloned = response.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(request, cloned));
            return response;
          });
      })
    );
  }
});
""".strip()

    response = HttpResponse(service_worker_js, content_type="application/javascript")
    response["Service-Worker-Allowed"] = "/"
    return response
