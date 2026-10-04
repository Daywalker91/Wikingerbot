"""Rang-Sync: Raenge der Community-Seite <-> Discord-Rollen (ohne Discord-Cog-
Abhaengigkeit, damit testbar).

Pro Rang: eine Discord-Rolle und eine Richtung
  both        Seite -> Discord und Discord -> Seite
  to_site     nur Discord -> Seite (z.B. Jarl <- Admin)
  to_discord  nur Seite -> Discord
  off         gar nicht (z.B. Koenig - bleibt Handarbeit)

Der Koenig hat immer "off". Seine Discord-Rolle ist nur eine Zuordnung: Der Bot
vergibt und entzieht sie nie, erkennt daran aber Konflikte beim Verknuepfen.

Regeln:
- Koenig wird nie automatisch vergeben, ein Koenig auf der Seite nie automatisch geaendert;
  ebenso wenig der Rang von jemandem, der in Discord die Koenig-Rolle hat.
- Seite -> Discord nur, wenn der Rang des Mitglieds Richtung both/to_discord hat;
  dann bekommt es die Rolle seines Rangs, die Rollen der anderen so gesyncten
  Raenge werden entfernt (Rang ohne Rolle, z.B. Thrall = @everyone: alle weg).
- Discord -> Seite: der hoechste Rang, dessen Rolle das Mitglied hat (Richtungen
  both/to_site); keine dieser Rollen = niedrigster Rang mit both/to_site.
- Wer Discord verlaesst, behaelt seinen Rang.
"""

import json
from dataclasses import dataclass

from sqlalchemy import select, update

from bot.community import db as community_db
from bot.core.guild_config import get_config, set_config

CONFIG_KEY = "rangsync_map"
DIRECTIONS = ("both", "to_site", "to_discord", "off")
# Standardvorschlag fuer die mitgelieferten Raenge der Community-Seite; die
# Discord-Rollen waehlt man im Tab
DEFAULT_DIRECTIONS = {"thrall": "both", "karl": "both", "huskarl": "both", "jarl": "to_site", "konig": "off"}
KING_SLUGS = {"konig", "koenig", "king"}


@dataclass
class Rank:
    id: int
    slug: str
    name: str
    level: int
    role_id: int | None = None
    direction: str = "off"

    @property
    def is_king(self) -> bool:
        return self.slug in KING_SLUGS

    @property
    def to_discord(self) -> bool:
        return self.direction in ("both", "to_discord") and not self.is_king

    @property
    def to_site(self) -> bool:
        return self.direction in ("both", "to_site") and not self.is_king


async def site_ranks() -> list[Rank]:
    r = community_db.roles
    query = await community_db.ranks_only(select(r.c.id, r.c.slug, r.c.name, r.c.level).order_by(r.c.level))
    async with community_db.session() as db:
        rows = (await db.execute(query)).all()
    return [Rank(*row) for row in rows]


async def load_mapping(guild_id: int) -> list[Rank]:
    try:
        stored = json.loads(await get_config(guild_id, CONFIG_KEY, "{}") or "{}")
    except json.JSONDecodeError:
        stored = {}
    ranks = await site_ranks()
    for rank in ranks:
        entry = stored.get(rank.slug, {})
        rank.role_id = int(entry["role_id"]) if entry.get("role_id") else None
        direction = entry.get("direction", DEFAULT_DIRECTIONS.get(rank.slug, "off"))
        rank.direction = direction if direction in DIRECTIONS else "off"
        if rank.is_king:
            rank.direction = "off"
    return ranks


async def save_mapping(guild_id: int, guild_name: str, mapping: dict[str, dict]) -> None:
    clean = {
        slug: {
            "role_id": int(v["role_id"]) if v.get("role_id") else None,
            "direction": v.get("direction") if v.get("direction") in DIRECTIONS else "off",
        }
        for slug, v in mapping.items()
    }
    await set_config(guild_id, CONFIG_KEY, json.dumps(clean), guild_name)


def target_discord_roles(ranks: list[Rank], user_rank_id: int, member_role_ids: set[int]) -> set[int] | None:
    """Neue Menge der Rollen-IDs des Mitglieds (Seite -> Discord) oder None = nicht anfassen."""
    rank = next((r for r in ranks if r.id == user_rank_id), None)
    if rank is None or not rank.to_discord:
        return None
    managed = {r.role_id for r in ranks if r.to_discord and r.role_id}
    result = set(member_role_ids) - managed
    if rank.role_id:
        result.add(rank.role_id)
    return result


def rank_from_discord(ranks: list[Rank], member_role_ids: set[int]) -> Rank | None:
    """Rang laut Discord-Rollen (Discord -> Seite) oder None, wenn nichts so gesynct wird."""
    candidates = [r for r in ranks if r.to_site]
    if not candidates:
        return None
    held = [r for r in candidates if r.role_id and r.role_id in member_role_ids]
    if held:
        return max(held, key=lambda r: r.level)
    roleless = [r for r in candidates if not r.role_id]
    return min(roleless, key=lambda r: r.level) if roleless else None


def holds_king_role(ranks: list[Rank], member_role_ids: set[int]) -> bool:
    """Hat das Mitglied die dem Koenig zugeordnete Discord-Rolle?"""
    return any(r.is_king and r.role_id and r.role_id in member_role_ids for r in ranks)


def has_any_rank_role(ranks: list[Rank], member_role_ids: set[int]) -> bool:
    return any(r.role_id and r.role_id in member_role_ids for r in ranks)


async def site_rank_of(site_user_id: int) -> int | None:
    u = community_db.users
    async with community_db.session() as db:
        return (await db.execute(select(u.c.role_id).where(u.c.id == site_user_id))).scalar_one_or_none()


async def set_site_rank(site_user_id: int, rank_id: int) -> None:
    u = community_db.users
    async with community_db.session() as db:
        await db.execute(update(u).where(u.c.id == site_user_id).values(role_id=rank_id))
        await db.commit()


async def linked_members() -> list[tuple[int, int, int]]:
    """(Seiten-ID, Discord-ID, Rang-ID) aller verknuepften, aktiven Konten."""
    u = community_db.users
    async with community_db.session() as db:
        rows = (
            await db.execute(
                select(u.c.id, u.c.discord_id, u.c.role_id).where(
                    u.c.discord_id.is_not(None), u.c.deleted_at.is_(None), u.c.is_banned == 0
                )
            )
        ).all()
    return [(r[0], r[1], r[2]) for r in rows]
