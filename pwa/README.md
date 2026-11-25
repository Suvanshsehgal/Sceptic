# Sceptic PWA

The Sceptic web portal as an installable progressive web app.

**The portal code is not modified.** This folder compiles the unchanged source in `../frontend` and adds only the PWA layer around the build, so the installed app and the web portal are the same application with the same pages, login and data. The two builds produce byte-identical portal bundles (same content hashes).

## What this folder adds

| File | Purpose |
|---|---|
| `src/manifest.webmanifest` | App name, colours, `standalone` display, icons |
| `src/sw.js` | Service worker: caches the app shell, shows it offline |
| `src/pwa-client.js` | Registers the worker, shows an install card and an update card |
| `icons/` | 192 and 512 px icons, a maskable icon, an Apple touch icon, an SVG |
| `scripts/make_icons.py` | Regenerates the PNG icons (needs matplotlib) |
| `scripts/check-pwa.mjs` | Checks the build for installability and cache safety |
| `vite.config.mjs` | Builds `../frontend` and injects the files above into `index.html` |

Nothing needs installing here: the build uses the tools in `../frontend/node_modules`. Run `npm install` in `../frontend` first if you have not.

## Use

```bash
cd pwa
npm run build      # outputs ./dist
npm run check      # 20 checks on the build
npm run preview    # serves ./dist at http://localhost:4174 (the backend is proxied from /api)
```

Open `http://localhost:4174` in Chrome or Edge. The install icon appears in the address bar, and a small "Install Sceptic as an app" card appears in the corner. `npm run dev` serves a development build at port 5174 without the service worker.

The portal expects the backend at `http://localhost:8000`. Set `VITE_API_URL` to point the proxy elsewhere.

## What is cached

- **Cached:** the portal's HTML shell and its hashed build files (`/assets/*`), plus the icons and manifest.
- **Never cached:** anything under `/api` or `/auth`, any non-GET request, any request with an `Authorization` header, and anything cross-origin (for example the Google Fonts stylesheet). Findings, deployments and login tokens always come live from the backend.
- **Offline:** the app shell opens, but data views need the backend. This is deliberate: stale audit results would be misleading.
- **Updates:** a new build is detected on the next visit and a card offers a reload. To force every client to drop its cache, change `CACHE_VERSION` in `src/sw.js`.

## Hosting it for real use

- **HTTPS is required.** Browsers register service workers only on HTTPS, with `localhost` as the one exception.
- Serve `dist/` as static files and send `/api/*` to the backend with the `/api` prefix stripped (what the proxy in `vite.config.mjs` does).
- Serve `sw.js` with `Cache-Control: no-cache` so updates are noticed.
- The existing `frontend/Dockerfile` runs the Vite dev server. That is separate from this folder and is not changed.

## Limits

- **Verified:** the build, 20 build checks (`npm run check`), identical portal bundle hashes to the plain frontend build, every PWA file served with the right type, and 12 tests (`npm run test:sw`) that run the real `sw.js` against a simulated cache and network, including offline behaviour and the rule that API and login traffic is never cached.
- **Not verified in a real browser:** the install prompt, the on-screen install and update cards, and the service worker's behaviour inside Chrome were not exercised, because the browser tool was not connected. Try `npm run preview` and check DevTools, Application, Service Workers and Manifest.
- iOS Safari installs through "Add to Home Screen" and does not show the install card.
