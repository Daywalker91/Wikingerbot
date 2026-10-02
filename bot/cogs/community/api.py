"""FastAPI-Router fuer die Community-Seite der Oberflaeche (web/CommunityPage.tsx):
Anbindung an die Datenbank der Community-Seite einstellen und pruefen.

Nur Datenbankname und Adresse der Seite - Host, Benutzer und Passwort sind die
der Bot-Datenbank (AMP-Felder DB_*) und werden hier nie angezeigt.
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from api.middleware.auth import CurrentUser, require_level
from bot.community import db as community_db
from bot.community import outbox
from bot.community.linking import linked_count
from bot.core.config import settings
from db.models.role import Level

router = APIRouter(prefix="/community", tags=["community"])


async def _status() -> dict:
    ok, message = await community_db.check_connection()
    data = {
        **community_db.current_config(),
        "db_host": settings.db_host or None,
        "connected": ok,
        "message": message,
        "linked": None,
        "pending": None,
        "failed": None,
        "handlers": outbox.registered(),
    }
    if ok:
        try:
            counts = await outbox.counts()
            data.update(linked=await linked_count(), pending=counts["pending"], failed=counts["failed"])
        except Exception:
            pass
    return data


@router.get("/config")
async def get_config(user: CurrentUser = Depends(require_level(Level.OWNER))) -> dict:
    return await _status()


class CommunityConfigIn(BaseModel):
    # MariaDB-Datenbanknamen: Buchstaben, Ziffern, _ und $ - nichts, was die URL verbiegt
    db_name: str = Field(default="", max_length=64, pattern=r"^[A-Za-z0-9_$]*$")
    site_url: str = Field(default="", max_length=200, pattern=r"^(https?://[^\s]+)?$")


@router.put("/config")
async def put_config(body: CommunityConfigIn, user: CurrentUser = Depends(require_level(Level.OWNER))) -> dict:
    await community_db.save_config(body.db_name, body.site_url)
    return await _status()
