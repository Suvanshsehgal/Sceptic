/*
 * Runs the real src/sw.js in a Node sandbox with a simulated Cache Storage and network, and checks each rule:
 * what is precached, what is never touched, what is cached, and what happens offline.
 *
 *   npm run test:sw
 */
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const source = fs.readFileSync(path.join(here, '..', 'src', 'sw.js'), 'utf8');
const ORIGIN = 'https://sceptic.test';

function basic(body, status = 200) {
  const response = new Response(body, { status });
  Object.defineProperty(response, 'type', { value: 'basic' });
  return response;
}

function makeWorld() {
  const stores = new Map();           // cache name -> Map(url -> Response)
  const calls = { fetch: [], skipWaiting: 0, claim: 0 };
  let online = true;
  const handlers = {};

  const keyOf = (req) => (typeof req === 'string' ? new URL(req, ORIGIN).href : req.url);
  const makeCache = (map) => ({
    async addAll(urls) { for (const u of urls) map.set(keyOf(u), basic(`shell:${u}`)); },
    async put(req, res) { map.set(keyOf(req), res); },
    async match(req) { const hit = map.get(keyOf(req)); return hit ? hit.clone() : undefined; },
  });

  const caches = {
    async open(name) { if (!stores.has(name)) stores.set(name, new Map()); return makeCache(stores.get(name)); },
    async keys() { return [...stores.keys()]; },
    async delete(name) { return stores.delete(name); },
    async match(req) {
      for (const map of stores.values()) { const hit = map.get(keyOf(req)); if (hit) return hit.clone(); }
      return undefined;
    },
  };

  const self = {
    location: { origin: ORIGIN },
    addEventListener(type, fn) { handlers[type] = fn; },
    skipWaiting() { calls.skipWaiting += 1; },
    clients: { async claim() { calls.claim += 1; } },
  };

  const context = vm.createContext({
    self, caches, URL, Response, Request, Promise,
    fetch: async (req) => {
      calls.fetch.push(typeof req === 'string' ? req : req.url);
      if (!online) throw new TypeError('offline');
      return basic(`network:${typeof req === 'string' ? req : req.url}`);
    },
  });
  vm.runInContext(source, context);

  return {
    stores, calls, handlers,
    setOnline(value) { online = value; },
    async install() { let p; handlers.install({ waitUntil: (x) => { p = x; } }); await p; },
    async activate() { let p; handlers.activate({ waitUntil: (x) => { p = x; } }); await p; },
    /** Returns the response if the worker handled the request, or null if it left it to the browser. */
    async fetch(url, { method = 'GET', headers = {}, mode = 'cors' } = {}) {
      const request = new Request(url, { method, headers });
      Object.defineProperty(request, 'mode', { value: mode });
      let handled = null;
      handlers.fetch({ request, respondWith: (p) => { handled = p; } });
      return handled ? await handled : null;
    },
  };
}

let passed = 0;
async function test(name, fn) {
  try { await fn(); passed += 1; console.log(`PASS  ${name}`); }
  catch (error) { console.log(`FAIL  ${name}\n      ${error.message}`); process.exitCode = 1; }
}

await test('install precaches the app shell', async () => {
  const w = makeWorld();
  await w.install();
  const shell = w.stores.get('sceptic-shell-v1');
  assert.ok(shell.has(`${ORIGIN}/`), 'index page cached');
  assert.ok(shell.has(`${ORIGIN}/manifest.webmanifest`), 'manifest cached');
});

await test('API requests are never handled', async () => {
  const w = makeWorld();
  for (const p of ['/api/audits', '/api/deployments/1/live', '/api']) {
    assert.equal(await w.fetch(`${ORIGIN}${p}`), null, p);
  }
  assert.equal(w.calls.fetch.length, 0);
});

await test('auth routes are never handled', async () => {
  const w = makeWorld();
  assert.equal(await w.fetch(`${ORIGIN}/auth/login`), null);
  assert.equal(await w.fetch(`${ORIGIN}/auth/me`), null);
});

await test('non-GET requests are never handled', async () => {
  const w = makeWorld();
  for (const method of ['POST', 'PATCH', 'DELETE']) assert.equal(await w.fetch(`${ORIGIN}/assets/a.js`, { method }), null, method);
});

await test('requests with an Authorization header are never handled', async () => {
  const w = makeWorld();
  assert.equal(await w.fetch(`${ORIGIN}/assets/a.js`, { headers: { Authorization: 'Bearer secret' } }), null);
});

await test('cross-origin requests (fonts) are never handled', async () => {
  const w = makeWorld();
  assert.equal(await w.fetch('https://fonts.googleapis.com/css2?family=Inter'), null);
});

await test('hashed assets are fetched once, then served from cache', async () => {
  const w = makeWorld();
  const first = await w.fetch(`${ORIGIN}/assets/index-abc123.js`);
  assert.equal(await first.text(), `network:${ORIGIN}/assets/index-abc123.js`);
  assert.equal(w.calls.fetch.length, 1);
  w.setOnline(false);
  const second = await w.fetch(`${ORIGIN}/assets/index-abc123.js`);
  assert.equal(await second.text(), `network:${ORIGIN}/assets/index-abc123.js`);
  assert.equal(w.calls.fetch.length, 1, 'no second network call');
});

await test('navigation is network first and refreshes the cached shell', async () => {
  const w = makeWorld();
  const res = await w.fetch(`${ORIGIN}/`, { mode: 'navigate' });
  assert.equal(await res.text(), `network:${ORIGIN}/`);
  const cached = await w.stores.get('sceptic-shell-v1').get(`${ORIGIN}/`).text();
  assert.equal(cached, `network:${ORIGIN}/`);
});

await test('offline navigation shows the cached shell', async () => {
  const w = makeWorld();
  await w.install();
  w.setOnline(false);
  const res = await w.fetch(`${ORIGIN}/`, { mode: 'navigate' });
  assert.equal(res.status, 200);
  assert.match(await res.text(), /^shell:/);
});

await test('offline navigation with nothing cached gives a clear 503', async () => {
  const w = makeWorld();
  w.setOnline(false);
  const res = await w.fetch(`${ORIGIN}/`, { mode: 'navigate' });
  assert.equal(res.status, 503);
  assert.match(await res.text(), /offline/i);
});

await test('activate removes old Sceptic caches only', async () => {
  const w = makeWorld();
  w.stores.set('sceptic-shell-v0', new Map());
  w.stores.set('sceptic-assets-v0', new Map());
  w.stores.set('another-app-cache', new Map());
  await w.install();
  await w.activate();
  assert.ok(!w.stores.has('sceptic-shell-v0') && !w.stores.has('sceptic-assets-v0'));
  assert.ok(w.stores.has('another-app-cache'), 'does not touch other apps');
  assert.ok(w.stores.has('sceptic-shell-v1'));
  assert.equal(w.calls.claim, 1);
});

await test('SKIP_WAITING message activates the new worker', async () => {
  const w = makeWorld();
  w.handlers.message({ data: { type: 'SKIP_WAITING' } });
  w.handlers.message({ data: { type: 'OTHER' } });
  assert.equal(w.calls.skipWaiting, 1);
});

console.log(`\n${passed} passed${process.exitCode ? ', some failed' : ''}.`);
