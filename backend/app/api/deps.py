from __future__ import annotations

from fastapi import HTTPException, Request


def remote_user(request: Request) -> str | None:
    """Anzeige/Audit – Authentifizierung macht Authelia vor Traefik."""
    return request.headers.get("Remote-User") or None


def not_found(what: str = "Nicht gefunden") -> HTTPException:
    return HTTPException(status_code=404, detail=what)
