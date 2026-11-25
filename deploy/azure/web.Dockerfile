# Builds the Sceptic portal as the installable PWA and serves it with Caddy, which also gets the HTTPS certificate.
# Build context: the repository root.
FROM node:20-slim AS build
WORKDIR /src
COPY frontend/package.json frontend/package-lock.json ./frontend/
RUN cd frontend && npm ci --no-audit --no-fund
COPY frontend ./frontend
COPY pwa ./pwa
# The PWA build compiles ../frontend unchanged and adds the manifest, service worker and icons.
RUN cd pwa && node ../frontend/node_modules/vite/bin/vite.js build --config vite.config.mjs

FROM caddy:2-alpine
COPY --from=build /src/pwa/dist /srv
COPY deploy/azure/Caddyfile /etc/caddy/Caddyfile
