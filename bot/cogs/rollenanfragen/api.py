"""FastAPI-Router fuer den Tab "Rollenanfragen": die letzten Anfragen der Seite mit Stand.
Entschieden wird in Discord (Knoepfe im Mod-Log und im Ticket-Thread)."""

from fastapi import APIRouter, Depends

from api.middleware.auth import CurrentUser, require_level
from bot.cogs.rollenanfragen.requests import recent
from bot.community import db as community_db
from bot.core import runtime
from bot.core.guild_config import get_config
from db.models.role import Level

router = APIRouter(prefix="/rollenanfragen", tags=["rollenanfragen"])


@router.get("")
async def list_requests(user: CurrentUser = Depends(require_level(Level.MOD))) -> dict:
    data = {
        "community_enabled": community_db.enabled(),
        "cog_loaded": bool(runtime.bot and runtime.bot.get_cog("RollenanfragenCog")),
        "modlog_set": bool(await get_config(user.guild_id, "modlog_channel_id")),
        "requests": [],
        "error": None,
    }
    if not community_db.enabled():
        return data
    try:
        rows = await recent(50)
    except Exception as error:  # z.B. Migration 011 noch nicht gelaufen oder Recht fehlt
        data["error"] = f"Rollenanfragen nicht lesbar: {str(error).splitlines()[0][:200]}"
        return data
    data["requests"] = [
        {
            "id": r.id,
            "member": r.username,
            "rank": r.requester_rank_name,
            "role": r.role_name,
            "kind": r.role_kind,
            "status": r.status,
            "reason": r.reason,
            "decided_by": r.decided_name,
            "note": r.decision_note,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "ticket_link": community_db.site_link("tickets.view", id=r.ticket_id) if r.ticket_id else None,
        }
        for r in rows
    ]
    return data
