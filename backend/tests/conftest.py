import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """Frische Umgebung: eigene Verzeichnisse + DB pro Test."""
    for name in ("config", "media", "sources"):
        (tmp_path / name).mkdir()
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("MEDIA_DIR", str(tmp_path / "media"))
    monkeypatch.setenv("SOURCES_DIR", str(tmp_path / "sources"))
    monkeypatch.setenv("TZ", "Europe/Berlin")
    from app import config, db
    s = config.reload_settings()
    s.ensure_dirs()
    db.migrate()
    yield tmp_path
