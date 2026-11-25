/*
 * Checks the built PWA in ./dist: installability requirements, file integrity, and that the service worker never
 * caches API or authentication traffic. Exits with code 1 if any check fails.
 *
 *   npm run build && npm run check
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const dist = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', 'dist');
let failures = 0;

function check(name, ok, detail = '') {
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? `  (${detail})` : ''}`);
  if (!ok) failures += 1;
}

function pngSize(file) {
  const buf = fs.readFileSync(file);
  const isPng = buf.slice(0, 8).equals(Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]));
  return isPng ? [buf.readUInt32BE(16), buf.readUInt32BE(20)] : null;
}

const exists = (p) => fs.existsSync(path.join(dist, p));
check('dist/index.html exists', exists('index.html'));
const html = exists('index.html') ? fs.readFileSync(path.join(dist, 'index.html'), 'utf8') : '';
check('index.html links the manifest', html.includes('rel="manifest"') && html.includes('/manifest.webmanifest'));
check('index.html sets a theme colour', html.includes('name="theme-color"'));
check('index.html loads the PWA client script', html.includes('/pwa-client.js'));
check('index.html still loads the portal bundle', /src="\/assets\/index-[\w-]+\.js"/.test(html));

let manifest = {};
try {
  manifest = JSON.parse(fs.readFileSync(path.join(dist, 'manifest.webmanifest'), 'utf8'));
} catch (error) {
  check('manifest parses as JSON', false, String(error));
}
check('manifest has name, start_url, display standalone',
  Boolean(manifest.name && manifest.start_url) && manifest.display === 'standalone');
const icons = manifest.icons || [];
for (const size of ['192x192', '512x512']) {
  const entry = icons.find((i) => i.sizes === size && i.type === 'image/png');
  check(`manifest declares a ${size} PNG icon`, Boolean(entry));
  if (entry) {
    const dims = exists(entry.src.slice(1)) ? pngSize(path.join(dist, entry.src.slice(1))) : null;
    check(`${entry.src} is a real PNG of that size`, Boolean(dims) && `${dims[0]}x${dims[1]}` === size,
      dims ? `${dims[0]}x${dims[1]}` : 'missing');
  }
}
check('manifest has a maskable icon', icons.some((i) => String(i.purpose).includes('maskable')));
for (const icon of icons) check(`icon file exists: ${icon.src}`, exists(icon.src.slice(1)));

const sw = exists('sw.js') ? fs.readFileSync(path.join(dist, 'sw.js'), 'utf8') : '';
check('service worker exists', sw.length > 0);
check('service worker never caches /api or /auth', sw.includes('NEVER_CACHE') && sw.includes('/^\\/api') && sw.includes('/^\\/auth'));
check('service worker only handles GET requests', sw.includes("request.method !== 'GET'"));
check('service worker skips requests that carry an Authorization header', sw.includes("request.headers.has('authorization')"));
check('service worker ignores cross-origin requests', sw.includes('url.origin !== self.location.origin'));

console.log(failures === 0 ? '\nAll checks passed.' : `\n${failures} check(s) failed.`);
process.exit(failures === 0 ? 0 : 1);
