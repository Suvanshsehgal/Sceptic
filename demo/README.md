# Demo site and control panel

A small service you can break on purpose, watched by Prometheus and Grafana.

- `site/` runs in Docker as `sceptic-demo-site` on port 8090. It exposes `/api/orders`, `/api/checkout`, `/health`, and `/metrics`.
- `control/` runs on your PC on port 8091. It stops, starts, pauses, and restarts the container, injects errors and latency, and sends test traffic.

## Start

From the project root, with Docker Desktop running:

```powershell
docker compose up -d --build demo-site prometheus grafana
.\venv\Scripts\python.exe -m uvicorn demo.control.app:app --port 8091
```

Open:
- Control panel: http://localhost:8091
- Grafana dashboard: http://localhost:3000, then **Dashboards → Sceptic - Demo Site Observability**
- Prometheus: http://localhost:9090

## What the buttons do

| Button | Effect |
|---|---|
| Stop / Start / Restart | `docker stop/start/restart sceptic-demo-site`. The service goes down completely. |
| Pause / Unpause | `docker pause/unpause`. The service freezes, so requests hang and time out. |
| Healthy | No faults. |
| Errors 30% / 100% | That share of `/api/*` requests returns HTTP 500. |
| Slow +2s | Adds 2 seconds to every `/api/*` request. |
| Meltdown | 60% errors plus 1.5 seconds of extra latency. |
| Custom sliders | Any error rate from 0 to 100 and any latency up to 5000 ms. |
| Send 20 / 100 | Sends test requests so the graphs have data. |

Fault settings stay until you change them. Check the Status card before you test.

## Notes

- The control panel runs on the host, not in a container. Controlling containers needs the Docker CLI, and mounting the Docker socket into a container would give it full control of Docker.
- The panel only allows the five container actions listed above.
- `/admin/fault` on the demo site has no login. Keep it on your local machine.
- Environment variables, if you need to change them: `DEMO_SITE_PORT` (default 8090), `DEMO_SITE_URL`, and `DEMO_CONTAINER_NAME`.
