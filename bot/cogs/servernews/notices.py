"""Ankuendigungen fuer Gameserver: Einstellungen, Texte, angekuendigte Neustarts/Wartungen.

Alle Zeitpunkte in der Datenbank sind UTC ohne Zeitzone; in Discord stehen sie als
Discord-Zeitstempel (<t:...>), die jeder in seiner eigenen Zeit sieht.
"""

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from bot.core.guild_config import get_config, set_config
from bot.core.timezone import community_timezone
from db.models.server import Server
from db.models.server_notice import ServerNotice
from db.session import get_db_session

DEFAULT_LEADS = [30, 10, 1]
KIND_TEXT = {
    "restart": ("🔄", "Neustart"),
    "update": ("⬆️", "Update mit Neustart"),
    "stop": ("⏹️", "Stopp"),
    "maintenance": ("🔧", "Wartung"),
}
# Bekannte Befehle fuer eine Nachricht an alle Spieler - nur Vorschlag, im Tab pruefbar ("Testen")
INGAME_SUGGESTIONS = (
    ("minecraft", "say {text}"),
    ("ark", "broadcast {text}"),
    ("rust", "say {text}"),
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def unix(at_utc: datetime) -> int:
    return int(at_utc.replace(tzinfo=timezone.utc).timestamp())


def local_to_utc(local: datetime) -> datetime:
    return local.replace(tzinfo=community_timezone()).astimezone(timezone.utc).replace(tzinfo=None)


def local_now() -> datetime:
    return datetime.now(community_timezone()).replace(tzinfo=None)


@dataclass
class Settings:
    channel_id: int | None = None
    ping_role_id: int | None = None
    leads: list[int] = field(default_factory=lambda: list(DEFAULT_LEADS))  # Minuten vorher, absteigend
    amp_schedule: bool = False  # Zeitplan aus AMP ankuendigen (erst nach Pruefung der Vorschau einschalten)
    outages: bool = True  # unerwartete Ausfaelle melden (ohne Ping)
    ingame: dict[str, str] = field(default_factory=dict)  # Server-ID -> Befehl mit {text}


def parse_leads(text: str) -> list[int]:
    """"30, 10, 1" -> [30, 10, 1] (1-1440 Minuten, absteigend, ohne Doppelte)."""
    values = {int(v) for v in re.findall(r"\d+", text or "") if 1 <= int(v) <= 1440}
    return sorted(values, reverse=True)[:6] or list(DEFAULT_LEADS)


async def load_settings(guild_id: int) -> Settings:
    try:
        ingame = json.loads(await get_config(guild_id, "servernews_ingame", "{}") or "{}")
    except json.JSONDecodeError:
        ingame = {}
    channel = await get_config(guild_id, "servernews_channel_id")
    role = await get_config(guild_id, "servernews_ping_role_id")
    return Settings(
        channel_id=int(channel) if channel else None,
        ping_role_id=int(role) if role else None,
        leads=parse_leads(await get_config(guild_id, "servernews_leads", "") or ""),
        amp_schedule=await get_config(guild_id, "servernews_amp_schedule", "false") == "true",
        outages=await get_config(guild_id, "servernews_outages", "true") == "true",
        ingame={str(k): str(v) for k, v in ingame.items() if isinstance(v, str)},
    )


async def save_settings(guild_id: int, guild_name: str, s: Settings) -> None:
    await set_config(guild_id, "servernews_channel_id", str(s.channel_id) if s.channel_id else "", guild_name)
    await set_config(guild_id, "servernews_ping_role_id", str(s.ping_role_id) if s.ping_role_id else "", guild_name)
    await set_config(guild_id, "servernews_leads", ",".join(str(v) for v in s.leads), guild_name)
    await set_config(guild_id, "servernews_amp_schedule", "true" if s.amp_schedule else "false", guild_name)
    await set_config(guild_id, "servernews_outages", "true" if s.outages else "false", guild_name)
    clean = {k: v.strip()[:200] for k, v in s.ingame.items() if v.strip()}
    await set_config(guild_id, "servernews_ingame", json.dumps(clean), guild_name)


def suggest_ingame(*names: str) -> str:
    text = " ".join(n.lower() for n in names if n)
    return next((cmd for key, cmd in INGAME_SUGGESTIONS if key in text), "")


def parse_start(text: str) -> datetime | None:
    """Startzeit aus "15" (Minuten ab jetzt) oder "20:00" (heute, sonst morgen) -> UTC."""
    text = (text or "").strip()
    if text.isdigit():
        minutes = int(text)
        return utcnow() + timedelta(minutes=minutes) if 0 <= minutes <= 7 * 1440 else None
    match = re.fullmatch(r"(\d{1,2})[:.](\d{2})", text)
    if not match or int(match[1]) > 23 or int(match[2]) > 59:
        return None
    now = local_now()
    when = now.replace(hour=int(match[1]), minute=int(match[2]), second=0, microsecond=0)
    if when <= now:
        when += timedelta(days=1)
    return local_to_utc(when)


# --- Texte -----------------------------------------------------------------------------


def announce_text(notice: ServerNotice, server_name: str, *, reminder: bool) -> str:
    icon, label = KIND_TEXT.get(notice.kind, KIND_TEXT["restart"])
    ts = unix(notice.at)
    if notice.kind == "maintenance":
        text = f"{icon} **{server_name}**: Wartung ab <t:{ts}:t> (<t:{ts}:R>)"
        if notice.duration_min:
            text += f", etwa {notice.duration_min} Minuten"
    else:
        verb = {"restart": "wird neu gestartet", "update": "wird aktualisiert und neu gestartet", "stop": "wird gestoppt"}.get(notice.kind, "wird neu gestartet")
        text = f"{icon} **{server_name}** {verb} – <t:{ts}:t> (<t:{ts}:R>)"
    if notice.reason:
        text += f" – {notice.reason}"
    elif notice.origin == "amp":
        text += " – geplant"
    return ("⏰ Erinnerung: " if reminder else "") + text


def ingame_text(notice: ServerNotice, minutes_left: int) -> str:
    _, label = KIND_TEXT.get(notice.kind, KIND_TEXT["restart"])
    when = "jetzt" if minutes_left <= 0 else f"in {minutes_left} Minute{'n' if minutes_left != 1 else ''}"
    return f"[Server] {label} {when}" + (f" - {notice.reason}" if notice.reason else "")


# --- Angekuendigte Neustarts/Wartungen ---------------------------------------------------


async def create_notice(guild_id: int, server_id: int, kind: str, at_utc: datetime, *, origin: str = "manual",
                        duration_min: int | None = None, reason: str | None = None, created_by: int | None = None,
                        amp_key: str | None = None) -> ServerNotice | None:
    """Neue Ankuendigung. Fuer den AMP-Zeitplan (amp_key) nur einmal je Lauf - sonst None."""
    async with get_db_session() as db:
        if amp_key and (await db.execute(select(ServerNotice.id).where(ServerNotice.amp_key == amp_key))).first():
            return None
        notice = ServerNotice(
            guild_id=guild_id, server_id=server_id, origin=origin, kind=kind, at=at_utc, duration_min=duration_min,
            reason=(reason or None) and reason[:200], created_by=created_by, status="pending", sent_leads="[]", amp_key=amp_key,
        )
        db.add(notice)
        await db.commit()
        await db.refresh(notice)
        return notice


async def open_notices(guild_id: int | None = None) -> list[tuple[ServerNotice, Server]]:
    async with get_db_session() as db:
        query = (
            select(ServerNotice, Server)
            .join(Server, Server.id == ServerNotice.server_id)
            .where(ServerNotice.status.in_(("pending", "running")))
            .order_by(ServerNotice.at)
        )
        if guild_id is not None:
            query = query.where(ServerNotice.guild_id == guild_id)
        return [(n, s) for n, s in (await db.execute(query)).all()]


async def set_status(notice_id: int, status: str, sent_leads: list[int] | None = None) -> None:
    async with get_db_session() as db:
        notice = await db.get(ServerNotice, notice_id)
        if notice is None:
            return
        notice.status = status
        if sent_leads is not None:
            notice.sent_leads = json.dumps(sorted(set(sent_leads), reverse=True))
        await db.commit()


def due_lead(notice: ServerNotice, leads: list[int], now: datetime) -> tuple[int | None, list[int]]:
    """Welche Vorlaufzeit jetzt dran ist (None = keine) und die danach gesendeten.
    Wird spaet angekuendigt (z.B. 12 Minuten vorher bei 30/10/1), gibt es EINE Meldung,
    und alle schon verstrichenen Stufen gelten als erledigt."""
    sent = set(json.loads(notice.sent_leads or "[]"))
    minutes_left = (notice.at - now).total_seconds() / 60
    open_leads = [lead for lead in leads if lead not in sent and minutes_left <= lead]
    if not open_leads:
        return None, sorted(sent, reverse=True)
    return min(open_leads), sorted(sent | set(open_leads), reverse=True)
