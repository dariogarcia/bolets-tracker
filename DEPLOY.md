# Deploying the Rovelló Tracker

How to run the server, from a laptop to a small VPS behind nginx.
The app is a single FastAPI process with no database: state lives in
`app/zones.py`, in-memory caches, and the two upstream APIs.

## Requirements

| Component | Version | Notes |
| --- | --- | --- |
| Python | 3.12+ | pinned in `pyproject.toml` |
| [uv](https://docs.astral.sh/uv/) | any recent | manages the venv and deps |
| Outbound HTTPS | — | to Open-Meteo, OSRM and Nominatim |

## Quick start (local)

```bash
git clone https://github.com/dariogarcia/bolets-tracker.git
cd bolets-tracker
uv sync                  # create .venv and install dependencies
uv run uvicorn app.main:app --port 8000
```

Open http://localhost:8000 — the UI, map tiles and API are all served
by the one process. Run the test suite before serving traffic:

```bash
uv run pytest            # 152 tests, no network needed
uv run ruff check .      # lint
```

## Production run

Serve on all interfaces with several workers. Each worker keeps its
own weather cache, so more workers means more upstream calls; two or
three is plenty for a small group of users.

```bash
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 3
```

### systemd unit

`/etc/systemd/system/bolets.service` (adjust paths and the user):

```ini
[Unit]
Description=Rovelló Tracker
After=network-online.target
Wants=network-online.target

[Service]
Type=exec
User=bolets
WorkingDirectory=/opt/bolets-tracker
ExecStart=/opt/bolets-tracker/.venv/bin/uvicorn app.main:app \
    --host 127.0.0.1 --port 8000 --workers 2
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now bolets
```

Note: `uv sync` in the app directory first, then point `ExecStart` at
`.venv/bin/uvicorn` as above so systemd does not depend on uv.

### nginx reverse proxy

```nginx
server {
    listen 80;
    server_name bolets.example.org;

    location /static/ {
        proxy_pass http://127.0.0.1:8000;
        expires 7d;                       # assets are content-hashed enough for a hobby deploy
    }

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        timeout 60s;                      # /api/recommend can take a few seconds
    }
}
```

Put HTTPS in front with `certbot --nginx`.

## Upstream APIs and rate limits

| Service | Used for | Limits / policy |
| --- | --- | --- |
| [Open-Meteo](https://open-meteo.com/) | forecast + archive weather | free, no key, ~10 000 calls/day for non-commercial use |
| [OSRM demo server](https://router.project-osrm.org/) | driving routes | public demo, no SLA — fine for a hobby deploy, self-host for anything serious |
| [Nominatim](https://nominatim.org/) | place search | max 1 req/s, provide a identifying User-Agent |

The app already reduces load on all three:

- weather lookups are deduplicated per ~0.1° grid cell across the 2,000 zones
- forecast responses are cached 30 min, archive responses 24 h
- route lookups are batched through OSRM's table service

For heavier use, self-host OSRM with a Catalonia/Spain `.osm.pbf`
(`osrm-data` on Docker makes this a two-command job) and point
`OSRM_URL`-equivalent constants in `app/routing.py` at it.

## Health check and monitoring

`GET /api/health` returns `{"status": "ok", "zones": <n>}` without
touching any upstream — use it for uptime checks:

```bash
curl -fsS http://localhost:8000/api/health
```

Logs go to stdout/journald (`journalctl -u bolets -f`).

## Updating the zone dataset

The dataset is fully GIS-derived (see README for the three-stage pipeline:
`build_forest_regions.py` → `enrich_regions.py` → `rebuild_zones_from_regions.py`),
with legacy curated lore inherited where regions contain an old staging
point. The workflow:

1. Regenerate the dataset (all stages above) — `app/zones.py`,
   `data/zone_polygons.json` and `data/forest_regions_attrs.json` change.
2. `uv run pytest` — the suite validates IDs, coordinates, polygons,
   inheritance and dataset size thresholds.
3. `uv run python scripts/export_static_data.py` to refresh
   `static/data/zones.json` for the static demo.
4. Restart the service (dataset is loaded at import time).

## GitHub Pages (static demo)

The UI is dual-mode: on load it probes `GET /api/health`. Served by the
FastAPI backend it uses the JSON API; on a static host (GitHub Pages) the
probe 404s and the browser computes everything itself through
`static/engine.js`, a JavaScript port of the scoring/weather/routing/
geocoding logic talking directly to Open-Meteo, the public OSRM server and
the Open-Meteo geocoder (all keyless, CORS-enabled). The zone dataset ships
as `static/data/zones.json` (regenerate with
`uv run python scripts/export_static_data.py` after touching `app/zones.py`).

The demo is served from the `gh-pages` branch of
`dariogarcia/bolets-tracker` (an orphan branch containing `index.html`,
`static/` and a `.nojekyll` marker). To republish after changes:

```bash
# from a checkout of the main branch
git checkout --orphan gh-pages
git rm -rq --cached .
rm -rf app tests scripts pyproject.toml uv.lock .python-version
cp static/index.html .          # the page must sit at the site root
printf '.nojekyll\n' > .nojekyll
git add -A
git commit -m "Rebuild GitHub Pages site"
git push -f origin gh-pages
git checkout main
```

A search in Pages mode costs the browser ~10 requests (weather grid cells
are batched 50 locations per request) plus one OSRM table batch per 94
sectors, comfortably inside the public APIs' limits.
