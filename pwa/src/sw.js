/*
 * Sceptic service worker.
 *
 * Caches only the application shell so the portal installs and opens quickly, and shows the shell when the device is
 * offline. It never caches API traffic, authentication, or anything that is not a same-origin GET, so findings,
 * deployments and tokens always come live from the backend.
 *
 * - Hashed build assets (/assets/*): cache first. Their file names change with their content, so they are immutable.
 * - Page navigations: network first, falling back to the cached shell when offline.
 * - Everything else: left to the browser.
 *
 * Change CACHE_VERSION to force every client to drop the old cache.
 */
const CACHE_VERSION = 'v1';
const SHELL_CACHE = `sceptic-shell-${CACHE_VERSION}`;
const ASSET_CACHE = `sceptic-assets-${CACHE_VERSION}`;
const SHELL_URLS = ['/', '/manifest.webmanifest', '/favicon.svg', '/icons/icon-192.png', '/icons/icon-512.png'];

// Paths that must always reach the network. Matches the API proxy prefix and the backend's auth routes.
const NEVER_CACHE = [/^\/api(\/|$)/, /^\/auth(\/|$)/];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(SHELL_CACHE).then((cache) => cache.addAll(SHELL_URLS)).catch(() => undefined),
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    (async () => {
      const keep = new Set([SHELL_CACHE, ASSET_CACHE]);
      const names = await caches.keys();
      await Promise.all(names.filter((name) => name.startsWith('sceptic-') && !keep.has(name)).map((name) => caches.delete(name)));
      await self.clients.claim();
    })(),
  );
});

// The page asks for the waiting worker to take over after the user accepts an update.
self.addEventListener('message', (event) => {
  if (event.data && event.data.type === 'SKIP_WAITING') {
    self.skipWaiting();
  }
});

self.addEventListener('fetch', (event) => {
  const request = event.request;
  if (request.method !== 'GET') return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  if (NEVER_CACHE.some((pattern) => pattern.test(url.pathname))) return;
  if (request.headers.has('authorization')) return;

  if (request.mode === 'navigate') {
    event.respondWith(
      (async () => {
        try {
          const fresh = await fetch(request);
          if (fresh.ok && fresh.type === 'basic') {
            const cache = await caches.open(SHELL_CACHE);
            cache.put('/', fresh.clone());
          }
          return fresh;
        } catch {
          const cached = await caches.match('/');
          return cached || new Response('Sceptic is offline and the app has not been cached yet.', {
            status: 503,
            headers: { 'Content-Type': 'text/plain; charset=utf-8' },
          });
        }
      })(),
    );
    return;
  }

  if (url.pathname.startsWith('/assets/')) {
    event.respondWith(
      (async () => {
        const cache = await caches.open(ASSET_CACHE);
        const hit = await cache.match(request);
        if (hit) return hit;
        const response = await fetch(request);
        if (response.ok && response.type === 'basic') cache.put(request, response.clone());
        return response;
      })(),
    );
  }
});
