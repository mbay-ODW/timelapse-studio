"""Uploads (Q-3): chunked mit Resume, ZIP-Entpacken, Alben als Quelle; Musik für P-20."""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import uuid
import zipfile
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from pydantic import BaseModel

from .. import config
from ..db import get_conn
from ..indexer.imageproc import SUPPORTED_EXT
from ..indexer.scanner import request_scan
from ..indexer.sources import UPLOAD_PREFIX, sync_sources

router = APIRouter(prefix="/api", tags=["uploads"])
MAX_FILE = 20 * 1024**3        # 20 GB pro Datei (ZIP)
MAX_CHUNK = 64 * 1024**2
AUDIO_EXT = {".mp3", ".m4a", ".aac", ".wav", ".flac", ".ogg", ".opus"}


def _incoming() -> Path:
    d = config.settings.uploads_dir / ".incoming"
    d.mkdir(parents=True, exist_ok=True)
    return d


def safe_album(name: str) -> str:
    s = re.sub(r"[^\w\- .äöüÄÖÜß]+", "_", name.strip()).strip(" ._")
    return s[:80] or "Upload"


def safe_filename(name: str) -> str:
    base = os.path.basename(name.replace("\\", "/"))
    s = re.sub(r"[^\w\-. ]+", "_", base).strip(" .")
    return s[:180] or "datei"


class InitIn(BaseModel):
    album: str
    filename: str
    size: int


@router.post("/uploads/init")
def init_upload(body: InitIn):
    ext = os.path.splitext(body.filename)[1].lower()
    if ext not in SUPPORTED_EXT and ext != ".zip":
        raise HTTPException(422, f"Dateityp {ext or '?'} nicht unterstützt")
    if body.size <= 0 or body.size > MAX_FILE:
        raise HTTPException(422, "Ungültige Dateigröße")
    album = safe_album(body.album)
    # deterministisch → erneutes Init nach Abbruch findet die Teildatei (Resume)
    uid = hashlib.sha1(f"{album}\0{body.filename}\0{body.size}".encode()).hexdigest()[:24]
    part = _incoming() / f"{uid}.part"
    (_incoming() / f"{uid}.meta").write_text(f"{album}\n{safe_filename(body.filename)}\n{body.size}\n", encoding="utf-8")
    return {"upload_id": uid, "offset": part.stat().st_size if part.exists() else 0, "chunk_size": 8 * 1024**2}


def _meta(uid: str) -> tuple[str, str, int]:
    if not re.fullmatch(r"[0-9a-f]{24}", uid):
        raise HTTPException(404, "Upload unbekannt")
    m = _incoming() / f"{uid}.meta"
    if not m.exists():
        raise HTTPException(404, "Upload unbekannt")
    album, name, size = m.read_text(encoding="utf-8").splitlines()[:3]
    return album, name, int(size)


@router.put("/uploads/{uid}")
async def put_chunk(uid: str, request: Request, offset: int):
    album, name, size = _meta(uid)
    part = _incoming() / f"{uid}.part"
    cur = part.stat().st_size if part.exists() else 0
    if offset != cur:
        raise HTTPException(409, detail={"offset": cur})
    written = 0
    with open(part, "ab") as f:
        async for chunk in request.stream():
            written += len(chunk)
            if written > MAX_CHUNK or cur + written > size:
                f.truncate(cur)
                raise HTTPException(413, "Chunk zu groß")
            f.write(chunk)
    new = cur + written
    if new < size:
        return {"offset": new, "done": False}
    return {"offset": new, "done": True, **_finalize(uid, album, name, part)}


def _unique(path: Path) -> Path:
    if not path.exists():
        return path
    stem, ext = path.stem, path.suffix
    i = 2
    while (p := path.with_name(f"{stem}-{i}{ext}")).exists():
        i += 1
    return p


def _finalize(uid: str, album: str, name: str, part: Path) -> dict:
    dest_dir = config.settings.uploads_dir / album
    dest_dir.mkdir(parents=True, exist_ok=True)
    added = 0
    try:
        if name.lower().endswith(".zip"):
            try:
                with zipfile.ZipFile(part) as z:
                    root = dest_dir.resolve()
                    for info in z.infolist():
                        if info.is_dir():
                            continue
                        rel = Path(*[safe_filename(p) for p in Path(info.filename).parts if p not in ("", ".", "..")])
                        if rel.suffix.lower() not in SUPPORTED_EXT or rel.name.startswith(("._", ".")) \
                                or "__MACOSX" in info.filename:
                            continue
                        target = _unique((root / rel).resolve())
                        if root not in target.parents:  # Zip-Slip-Schutz
                            continue
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with z.open(info) as src, open(target, "wb") as dst:
                            shutil.copyfileobj(src, dst, 1024 * 1024)
                        added += 1
            except zipfile.BadZipFile:
                raise HTTPException(422, "ZIP-Archiv ist beschädigt")
            part.unlink(missing_ok=True)
        else:
            os.replace(part, _unique(dest_dir / name))
            added = 1
    finally:
        (_incoming() / f"{uid}.meta").unlink(missing_ok=True)
    sync_sources()
    row = get_conn().execute("SELECT id FROM source WHERE name=?", (UPLOAD_PREFIX + album,)).fetchone()
    if row:
        request_scan(row["id"])
    return {"album": album, "files_added": added, "source_id": row["id"] if row else None}


@router.delete("/uploads/{uid}")
def abort_upload(uid: str):
    _meta(uid)
    (_incoming() / f"{uid}.part").unlink(missing_ok=True)
    (_incoming() / f"{uid}.meta").unlink(missing_ok=True)
    return {"ok": True}


@router.get("/uploads/albums")
def albums():
    sync_sources()
    rows = get_conn().execute(
        "SELECT s.id, s.display_name, (SELECT COUNT(*) FROM image i WHERE i.source_id=s.id) n FROM source s"
        " WHERE kind='upload' ORDER BY display_name").fetchall()
    return [{"source_id": r["id"], "name": r["display_name"], "images": r["n"]} for r in rows]


@router.post("/audio")
async def upload_audio(file: UploadFile = File(...)):
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in AUDIO_EXT:
        raise HTTPException(422, "Audioformat nicht unterstützt (mp3, m4a, aac, wav, flac, ogg, opus)")
    d = config.settings.uploads_dir / ".audio"
    d.mkdir(parents=True, exist_ok=True)
    fid = f"{uuid.uuid4().hex}{ext}"
    size = 0
    with open(d / fid, "wb") as out:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > 200 * 1024**2:
                out.close()
                (d / fid).unlink(missing_ok=True)
                raise HTTPException(413, "Audiodatei zu groß (max. 200 MB)")
            out.write(chunk)
    return {"file": fid, "name": safe_filename(file.filename or fid)}
