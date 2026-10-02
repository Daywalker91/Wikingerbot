"""Zaehler fuer den stats-Cog - sammelt im Speicher, schreibt einmal pro Minute.

Ohne Discord-Abhaengigkeit, damit testbar. Tage werden in Europe/Vienna
gezaehlt (der Bot laeuft in AMP oft in UTC - "heute" soll aber der Tag der
Community sein).
"""

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import delete, func, select

from bot.core.entities import ensure_guild
from db.models.stats import StatsDaily, StatsMemberDaily
from db.session import get_db_session

TZ = ZoneInfo("Europe/Vienna")


def now() -> datetime:
    return datetime.now(TZ)


def today() -> date:
    return now().date()


def split_by_day(start: datetime, end: datetime) -> list[tuple[date, int]]:
    """Voice-Zeit ueber Mitternacht korrekt auf die Tage verteilen."""
    parts = []
    cursor = start
    while cursor.date() < end.date():
        midnight = datetime.combine(cursor.date() + timedelta(days=1), datetime.min.time(), tzinfo=cursor.tzinfo)
        parts.append((cursor.date(), int((midnight - cursor).total_seconds())))
        cursor = midnight
    seconds = int((end - cursor).total_seconds())
    if seconds > 0 or not parts:
        parts.append((cursor.date(), max(seconds, 0)))
    return parts


class StatsBuffer:
    def __init__(self) -> None:
        self.daily: dict[tuple[int, date], Counter] = defaultdict(Counter)
        self.member: dict[tuple[int, int, date], Counter] = defaultdict(Counter)
        self.guild_names: dict[int, str] = {}

    def message(self, guild_id: int, user_id: int, day: date) -> None:
        self.daily[(guild_id, day)]["messages"] += 1
        self.member[(guild_id, user_id, day)]["messages"] += 1

    def join(self, guild_id: int, day: date) -> None:
        self.daily[(guild_id, day)]["joins"] += 1

    def leave(self, guild_id: int, day: date) -> None:
        self.daily[(guild_id, day)]["leaves"] += 1

    def voice(self, guild_id: int, user_id: int, start: datetime, end: datetime) -> None:
        for day, seconds in split_by_day(start, end):
            if seconds <= 0:
                continue
            self.daily[(guild_id, day)]["voice_seconds"] += seconds
            self.member[(guild_id, user_id, day)]["voice_seconds"] += seconds

    def drain(self):
        daily, member = self.daily, self.member
        self.daily, self.member = defaultdict(Counter), defaultdict(Counter)
        return daily, member


async def flush(buffer: StatsBuffer) -> None:
    daily, member = buffer.drain()
    if not daily and not member:
        return
    for guild_id in {key[0] for key in daily} | {key[0] for key in member}:
        await ensure_guild(guild_id, buffer.guild_names.get(guild_id, str(guild_id)))
    async with get_db_session() as db:
        for (guild_id, day), counts in daily.items():
            row = await db.get(StatsDaily, (guild_id, day))
            if row is None:
                row = StatsDaily(guild_id=guild_id, day=day, joins=0, leaves=0, messages=0, voice_seconds=0)
                db.add(row)
            for field, value in counts.items():
                setattr(row, field, getattr(row, field) + value)
        for (guild_id, user_id, day), counts in member.items():
            row = await db.get(StatsMemberDaily, (guild_id, user_id, day))
            if row is None:
                row = StatsMemberDaily(guild_id=guild_id, user_id=user_id, day=day, messages=0, voice_seconds=0)
                db.add(row)
            for field, value in counts.items():
                setattr(row, field, getattr(row, field) + value)
        await db.commit()


async def purge_member_rows(older_than_days: int) -> int:
    cutoff = today() - timedelta(days=older_than_days)
    async with get_db_session() as db:
        result = await db.execute(delete(StatsMemberDaily).where(StatsMemberDaily.day < cutoff))
        await db.commit()
        return result.rowcount or 0


# --- Auswertung -----------------------------------------------------------------


async def server_summary(guild_id: int, days: int) -> dict:
    since = today() - timedelta(days=days - 1)
    async with get_db_session() as db:
        totals = (
            await db.execute(
                select(
                    func.coalesce(func.sum(StatsDaily.joins), 0),
                    func.coalesce(func.sum(StatsDaily.leaves), 0),
                    func.coalesce(func.sum(StatsDaily.messages), 0),
                    func.coalesce(func.sum(StatsDaily.voice_seconds), 0),
                ).where(StatsDaily.guild_id == guild_id, StatsDaily.day >= since)
            )
        ).one()
        busiest = (
            await db.execute(
                select(StatsDaily.day, StatsDaily.messages)
                .where(StatsDaily.guild_id == guild_id, StatsDaily.day >= since)
                .order_by(StatsDaily.messages.desc())
                .limit(1)
            )
        ).first()
        top_messages = await _top(db, guild_id, since, StatsMemberDaily.messages)
        top_voice = await _top(db, guild_id, since, StatsMemberDaily.voice_seconds)
    return {
        "joins": int(totals[0]),
        "leaves": int(totals[1]),
        "messages": int(totals[2]),
        "voice_seconds": int(totals[3]),
        "busiest_day": (busiest[0], busiest[1]) if busiest and busiest[1] else None,
        "top_messages": top_messages,
        "top_voice": top_voice,
    }


async def _top(db, guild_id: int, since: date, column, limit: int = 5) -> list[tuple[int, int]]:
    total = func.sum(column)
    rows = await db.execute(
        select(StatsMemberDaily.user_id, total)
        .where(StatsMemberDaily.guild_id == guild_id, StatsMemberDaily.day >= since)
        .group_by(StatsMemberDaily.user_id)
        .having(total > 0)
        .order_by(total.desc())
        .limit(limit)
    )
    return [(int(user_id), int(value)) for user_id, value in rows.all()]


async def member_summary(guild_id: int, user_id: int, days: int) -> dict:
    since = today() - timedelta(days=days - 1)
    async with get_db_session() as db:
        row = (
            await db.execute(
                select(
                    func.coalesce(func.sum(StatsMemberDaily.messages), 0),
                    func.coalesce(func.sum(StatsMemberDaily.voice_seconds), 0),
                ).where(
                    StatsMemberDaily.guild_id == guild_id,
                    StatsMemberDaily.user_id == user_id,
                    StatsMemberDaily.day >= since,
                )
            )
        ).one()
        messages = int(row[0])
        totals = select(func.sum(StatsMemberDaily.messages).label("m")).where(
            StatsMemberDaily.guild_id == guild_id, StatsMemberDaily.day >= since
        ).group_by(StatsMemberDaily.user_id).subquery()
        ahead = (await db.execute(select(func.count()).select_from(totals).where(totals.c.m > messages))).scalar_one()
    return {"messages": messages, "voice_seconds": int(row[1]), "rank": int(ahead) + 1 if messages else None}


def format_duration(seconds: int) -> str:
    hours, rest = divmod(int(seconds), 3600)
    return f"{hours} h {rest // 60:02d} min" if hours else f"{rest // 60} min"
