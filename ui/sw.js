/* JARVIS service worker: app-shell cache для PWA-режима.
 * Кэшируются только статические ассеты GET same-origin.
 * RPC (/rpc), /stt и любые POST не кэшируются и не перехватываются.
 */

var CACHE = "jarvis-shell-v4";
var SHELL = [
  "./",
  "./index.html",
  "./css/fonts.css",
  "./css/tokens.css",
  "./assets/fonts/Orbitron-Variable.ttf",
  "./assets/fonts/Exo2-Variable.ttf",
  "./assets/fonts/JetBrainsMono-Variable.ttf",
  "./css/base.css",
  "./css/layout.css",
  "./css/components.css",
  "./css/pages.css",
  "./js/api.js",
  "./js/utils.js",
  "./js/reactor.js",
  "./js/app.js",
  "./manifest.webmanifest"
];

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
  /* API и health не кэшируем — всегда сеть */
  if (url.pathname === "/rpc" || url.pathname === "/stt" || url.pathname === "/health") {
    return;
  }
  /* Статика: network-first, при офлайне — из кэша */
  event.respondWith(
    fetch(request)
      .then(function (response) {
        if (response && response.ok) {
          var clone = response.clone();
          caches.open(CACHE).then(function (cache) {
            cache.put(request, clone);
          });
        }
        return response;
      })
      .catch(function () {
        return caches.match(request).then(function (cached) {
          return cached || caches.match("./index.html");
        });
      })
  );
});
