"""Laufzeitkonfiguration ausschließlich per ENV (siehe docs/requirements.md §3)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def _default_threads() -> int:
    return max(1, (os.cpu_count() or 2) - 1)


@dataclass(frozen=True)
class Settings:
    tz: str = field(default_factory=lambda: os.environ.get("TZ", "Europe/Berlin"))
    # Kleine, kritische Daten (DB) → /mnt/apps/timelapse
    config_dir: Path = field(default_factory=lambda: Path(os.environ.get("CONFIG_DIR", "/config")))
    # Große Nutzdaten (thumbs, proxies, uploads, renders, tmp) → /mnt/bulk/timelapse-studio
    media_dir: Path = field(default_factory=lambda: Path(os.environ.get("MEDIA_DIR", "/media")))
    # Read-only Bildquellen
    sources_dir: Path = field(default_factory=lambda: Path(os.environ.get("SOURCES_DIR", "/sources")))
    max_parallel_renders: int = field(default_factory=lambda: _int("MAX_PARALLEL_RENDERS", 1))
    ffmpeg_threads: int = field(default_factory=lambda: _int("FFMPEG_THREADS", _default_threads()))
    thumb_size: int = field(default_factory=lambda: _int("THUMB_SIZE", 320))
    proxy_size: int = field(default_factory=lambda: _int("PROXY_SIZE", 960))
    index_workers: int = field(default_factory=lambda: _int("INDEX_WORKERS", max(1, (os.cpu_count() or 2) - 2)))
    hwaccel: str = field(default_factory=lambda: os.environ.get("HWACCEL", "none").lower())
    vaapi_device: str = field(default_factory=lambda: os.environ.get("VAAPI_DEVICE", "/dev/dri/renderD128"))
    # z. B. "22:00-06:00" – große Render-Jobs nur in diesem Fenster; leer = immer
    render_window: str = field(default_factory=lambda: os.environ.get("RENDER_WINDOW", "").strip())
    ntfy_url: str = field(default_factory=lambda: os.environ.get("NTFY_URL", "").rstrip("/"))
    ntfy_topic: str = field(default_factory=lambda: os.environ.get("NTFY_TOPIC", ""))
    ntfy_token: str = field(default_factory=lambda: os.environ.get("NTFY_TOKEN", ""))
    renders_retention_days: int = field(default_factory=lambda: _int("RENDERS_RETENTION_DAYS", 0))
    log_level: str = field(default_factory=lambda: os.environ.get("LOG_LEVEL", "INFO").upper())

    @property
    def db_path(self) -> Path:
        return self.config_dir / "timelapse.db"

    @property
    def thumbs_dir(self) -> Path:
        return self.media_dir / "thumbs"

    @property
    def proxies_dir(self) -> Path:
        return self.media_dir / "proxies"

    @property
    def uploads_dir(self) -> Path:
        return self.media_dir / "uploads"

    @property
    def renders_dir(self) -> Path:
        return self.media_dir / "renders"

    @property
    def tmp_dir(self) -> Path:
        return self.media_dir / "tmp"

    def ensure_dirs(self) -> None:
        for d in (self.config_dir, self.thumbs_dir, self.proxies_dir, self.uploads_dir,
                  self.renders_dir, self.tmp_dir):
            d.mkdir(parents=True, exist_ok=True)


settings = Settings()


def reload_settings() -> Settings:
    """Liest ENV neu ein (Tests, Worker-Start)."""
    global settings
    settings = Settings()
    return settings
