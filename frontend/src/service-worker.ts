/// <reference types="@sveltejs/kit" />
/// <reference no-default-lib="true"/>
/// <reference lib="esnext" />
/// <reference lib="webworker" />

import { build, files, version } from "$service-worker";

const sw = self as unknown as ServiceWorkerGlobalScope;

const CACHE = `cache-${version}`;

const ASSETS = [
  ...build, // the app itself (JS/CSS bundles, and the fonts beside them)
  ...files, // everything in `static`
];
const ASSET_SET = new Set(ASSETS);

/** Built files carry a hash of their content in their name: one that an
 *  older version cached is the same file. */
const IMMUTABLE = "/_app/immutable/";

/*
 * What is fetched ahead, when the worker installs: the app's shell. Not
 * the typefaces — some 330 slices, 15 MB, of which a page uses a handful:
 * those are cached when they are first asked for (the fetch handler
 * below), which keeps what a reader has actually used available offline.
 */
const ON_FIRST_USE = /\.woff2?$/;
const AHEAD = ASSETS.filter((path) => !ON_FIRST_USE.test(path));

/** A new version's cache starts from what the older ones hold of the
 *  same files, and fetches only the rest: a deploy costs a visitor the
 *  files that changed, not the whole app again. */
async function fill(cache: Cache) {
  for (const name of await caches.keys()) {
    if (name === CACHE) continue;
    const old = await caches.open(name);
    for (const request of await old.keys()) {
      const { pathname } = new URL(request.url);
      if (!pathname.startsWith(IMMUTABLE) || !ASSET_SET.has(pathname)) continue;
      const response = await old.match(request);
      if (response) await cache.put(request, response);
    }
  }
  const missing: string[] = [];
  for (const path of AHEAD) if (!(await cache.match(path))) missing.push(path);
  await cache.addAll(missing);
}

sw.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(CACHE)
      .then(fill)
      .then(() => sw.skipWaiting()),
  );
});

sw.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then(async (keys) => {
      for (const key of keys) {
        if (key !== CACHE) await caches.delete(key);
      }
      await sw.clients.claim();
    }),
  );
});

// Respond to health-check pings from the app (iOS PWA resume detection)
sw.addEventListener("message", (event) => {
  if (event.data?.type === "ping" && event.ports[0]) {
    event.ports[0].postMessage({ type: "pong" });
  }
});

sw.addEventListener("fetch", (event) => {
  if (event.request.method !== "GET") return;

  const url = new URL(event.request.url);

  // Don't cache API calls or auth endpoints
  if (url.pathname.startsWith("/api/")) return;

  const isAsset = ASSET_SET.has(url.pathname);
  const isCover = url.pathname.startsWith("/covers/");

  if (isAsset || isCover) {
    // Cache-first for static assets and cover images
    event.respondWith(
      caches.match(event.request).then(
        (cached) =>
          cached ??
          fetch(event.request).then((response) => {
            if (response.status === 200) {
              const clone = response.clone();
              caches
                .open(CACHE)
                .then((cache) => cache.put(event.request, clone));
            }
            return response;
          }),
      ),
    );
  } else {
    // Network-first for pages
    event.respondWith(
      fetch(event.request)
        .then((response) => {
          if (response.status === 200) {
            const clone = response.clone();
            caches.open(CACHE).then((cache) => cache.put(event.request, clone));
          }
          return response;
        })
        .catch(() => caches.match(event.request).then((cached) => cached!)),
    );
  }
});
