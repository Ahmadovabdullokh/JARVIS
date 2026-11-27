/* JARVIS service worker: app-shell cache для PWA-режима.
 * HTML — network-first; ассеты с ?v=<hash> неизменяемы — cache-first;
 * прочая статика — stale-while-revalidate. RPC (/rpc), /stt и любые
 * POST не кэшируются и не перехватываются.
 */

var CACHE = "jarvis-shell-v7";
var SHELL = [
  "./",
  "./index.html",
  "./manifest.webmanifest"
];

function remember(request, response) {
  if (!response || !response.ok) return;
  var clone = response.clone();
  caches.open(CACHE).then(function (cache) {
    cache.put(request, clone);
  });
}

function offline() {
  return new Response("JARVIS недоступен без сети.", {
    status: 503,
    headers: { "Content-Type": "text/plain; charset=utf-8" }
  });
}

self.addEventListener("install", function (event) {
  event.waitUntil(
    caches.open(CACHE).then(function (cache) {
      return cache.addAll(SHELL).catch(function () {
        /* частичный кэш допустим — страница откроется и так */
      });
    })
  );
  self.skipWaiting();
});

self.addEventListener("activate", function (event) {
  event.waitUntil(
    caches.keys().then(function (keys) {
      return Promise.all(
        keys
          .filter(function (key) { return key !== CACHE; })
          .map(function (key) { return caches.delete(key); })
      );
    })
  );
  self.clients.claim();
});

self.addEventListener("fetch", function (event) {
  var request = event.request;
  if (request.method !== "GET") {
    return;
  }
  var url = new URL(request.url);
  if (url.origin !== self.location.origin) {
    return;
  }
  /* API, health и MJPEG-поток не кэшируем — всегда сеть */
  if (url.pathname === "/rpc" || url.pathname === "/stt" ||
      url.pathname === "/health" || url.pathname === "/camera.mjpg" ||
      url.pathname === "/camera/frame") {
    return;
  }

  if (request.mode === "navigate") {
    /* HTML: свежий index с новыми хэшами, кэш — только офлайн. */
    event.respondWith(
      fetch(request)
        .then(function (response) {
          remember(request, response);
          return response;
        })
        .catch(function () {
          return caches.match(request).then(function (cached) {
            return cached || caches.match("./index.html") || offline();
          });
        })
    );
    return;
  }

  if (url.searchParams.has("v")) {
    /* Версионированный ассет неизменяем — сразу из кэша. */
    event.respondWith(
      caches.match(request).then(function (cached) {
        if (cached) return cached;
        return fetch(request).then(function (response) {
          remember(request, response);
          return response;
        }).catch(offline);
      })
    );
    return;
  }

  /* Остальная статика: отдать кэш и обновить его на фоне. */
  event.respondWith(
    caches.match(request).then(function (cached) {
      var network = fetch(request)
        .then(function (response) {
          remember(request, response);
          return response;
        })
        .catch(function () {
          return cached || offline();
        });
      return cached || network;
    })
  );
});
