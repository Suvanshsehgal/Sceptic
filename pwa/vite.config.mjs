/*
 * Builds the Sceptic web portal as a progressive web app WITHOUT touching the frontend code.
 *
 * It compiles the unchanged source in ../frontend, so the installed app and the web portal are the same
 * application. This config adds only the PWA layer around that build: a web app manifest, a service worker,
 * icons, and a small client script that registers the worker and offers install and update prompts.
 *
 * Plugins and tools are resolved from ../frontend/node_modules, so there is nothing extra to install.
 * Run it with `npm run build` and `npm run preview` from this folder.
 */
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath, pathToFileURL } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const frontend = path.resolve(here, '../frontend');
const fromFrontend = createRequire(path.join(frontend, 'package.json'));

async function loadFromFrontend(name) {
  return import(pathToFileURL(fromFrontend.resolve(name)).href);
}

const { default: react, reactCompilerPreset } = await loadFromFrontend('@vitejs/plugin-react');
const { default: tailwindcss } = await loadFromFrontend('@tailwindcss/vite');
const { default: babel } = await loadFromFrontend('@rolldown/plugin-babel');

const PWA_FILES = [
  ['src/manifest.webmanifest', 'manifest.webmanifest'],
  ['src/sw.js', 'sw.js'],
  ['src/pwa-client.js', 'pwa-client.js'],
  ['icons/icon-192.png', 'icons/icon-192.png'],
  ['icons/icon-512.png', 'icons/icon-512.png'],
  ['icons/maskable-512.png', 'icons/maskable-512.png'],
  ['icons/apple-touch-icon.png', 'icons/apple-touch-icon.png'],
  ['icons/icon.svg', 'icons/icon.svg'],
];

function scepticPwa() {
  return {
    name: 'sceptic-pwa',
    // Adds the manifest, theme colour, Apple tags and the client script to the portal's index.html.
    transformIndexHtml() {
      return [
        { tag: 'link', attrs: { rel: 'manifest', href: '/manifest.webmanifest' }, injectTo: 'head' },
        { tag: 'link', attrs: { rel: 'apple-touch-icon', href: '/icons/apple-touch-icon.png' }, injectTo: 'head' },
        { tag: 'link', attrs: { rel: 'icon', type: 'image/png', sizes: '192x192', href: '/icons/icon-192.png' }, injectTo: 'head' },
        { tag: 'meta', attrs: { name: 'theme-color', content: '#0c0d0f' }, injectTo: 'head' },
        { tag: 'meta', attrs: { name: 'mobile-web-app-capable', content: 'yes' }, injectTo: 'head' },
        { tag: 'meta', attrs: { name: 'apple-mobile-web-app-capable', content: 'yes' }, injectTo: 'head' },
        { tag: 'meta', attrs: { name: 'apple-mobile-web-app-title', content: 'Sceptic' }, injectTo: 'head' },
        { tag: 'script', attrs: { src: '/pwa-client.js', defer: true }, injectTo: 'body' },
      ];
    },
    // Copies the PWA files into the build output under fixed names (a service worker must not be hashed).
    generateBundle() {
      for (const [from, to] of PWA_FILES) {
        this.emitFile({ type: 'asset', fileName: to, source: fs.readFileSync(path.join(here, from)) });
      }
    },
  };
}

const apiProxy = {
  '/api': {
    target: process.env.VITE_API_URL || 'http://localhost:8000',
    changeOrigin: true,
    rewrite: (p) => p.replace(/^\/api/, ''),
  },
};

export default {
  root: frontend,
  publicDir: path.join(frontend, 'public'),
  plugins: [react(), tailwindcss(), babel({ presets: [reactCompilerPreset()] }), scepticPwa()],
  build: { outDir: path.join(here, 'dist'), emptyOutDir: true },
  server: { host: '0.0.0.0', port: 5174, proxy: apiProxy },
  preview: { host: '0.0.0.0', port: 4174, proxy: apiProxy },
};
