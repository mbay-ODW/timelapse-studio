# Timelapse Studio

Self-hosted Web-App, um aus großen Bildserien (Kamera-Snapshots, Uploads) Zeitraffer-Videos zu erstellen:
Bilder Immich-ähnlich durchsuchen → Auswahl per Regeln → Parameter → Sofort-Preview → Render-Job → Download.

Anforderungen: [`docs/requirements.md`](docs/requirements.md)

## Architektur

- **Backend:** Python 3.12, FastAPI, SQLite (WAL), Pillow (JPEG-Draft-Decoding), numpy für die Auswahl-Pipeline
- **Worker:** eigener Prozess (gleiches Image): Quellen-Scan, Thumbnails, Render-Queue (ffmpeg)
- **Frontend:** React + Vite, als statische Dateien vom Backend ausgeliefert (keine CDNs)
- **Auth:** keine eigene – gedacht für einen Reverse-Proxy mit ForwardAuth (z. B. Authelia); `Remote-User` wird nur angezeigt

## Mounts

| Container | Inhalt | Empfehlung |
|---|---|---|
| `/config` | SQLite-DB (Projekte, Presets, Regeln, Queue, Index) | schneller App-Pool |
| `/media` | `thumbs/ proxies/ uploads/ renders/ tmp/` | großer Daten-Pool, eigenes Dataset |
| `/sources/<name>` | Bildquellen, **read-only** | `:ro` |

## Konfiguration (ENV)

| Variable | Default | Bedeutung |
|---|---|---|
| `PUID` / `PGID` | 568 | Laufzeit-User |
| `HWACCEL` | `none` | `none` \| `vaapi` \| `qsv` |
| `MAX_PARALLEL_RENDERS` | 1 | gleichzeitige Render-Jobs |
| `FFMPEG_THREADS` | Kerne − 1 | Threads pro ffmpeg |
| `INDEX_WORKERS` | Kerne − 2 | Prozesse für Thumbnails |
| `THUMB_SIZE` | 320 | lange Kante der Thumbnails |
| `RENDER_WINDOW` | leer | z. B. `22:00-06:00` – finale Renders nur in diesem Fenster |
| `SCAN_INTERVAL_MIN` | 60 | automatischer Rescan (0 = aus) |
| `RENDERS_RETENTION_DAYS` | 0 | Auto-Cleanup fertiger Renders (0 = aus) |
| `NTFY_URL` / `NTFY_TOPIC` / `NTFY_TOKEN` | leer | Benachrichtigung bei Job-Ende |
| `DOMAIN` | – | Hostname für den Traefik-Router |
| `CONFIG_PATH` / `MEDIA_PATH` / `SNAPSHOT_SOURCE` | – | Host-Pfade der Mounts |

## Entwicklung

```bash
python3.12 -m venv .venv && .venv/bin/pip install -r backend/requirements-dev.txt
.venv/bin/pytest backend/tests
cd frontend && npm ci && npm run dev   # Proxy auf :8080
```

## Deploy (lokal gebautes Image)

1. Quellen als Tarball auf den Docker-Host kopieren, dort `docker build -t timelapse-studio:latest .`
2. Stack aus `docker-compose.yml` anlegen bzw. aktualisieren (Portainer, `pullImage: false`)
3. Stack-ENV: mindestens `DOMAIN`, `CONFIG_PATH`, `MEDIA_PATH`, `SNAPSHOT_SOURCE`
