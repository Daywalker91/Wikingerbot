"""stats-Cog: Tagesaufteilung, Puffer, Speichern und Auswertung."""

from datetime import datetime, timedelta
from types import SimpleNamespace

from bot.cogs.stats.cog import counter_name
from bot.cogs.stats.collector import (
    TZ,
    StatsBuffer,
    flush,
    format_duration,
    member_summary,
    purge_member_rows,
    server_summary,
    split_by_day,
    today,
)
from db.models.stats import StatsMemberDaily


def test_split_by_day_same_day():
    start = datetime(2026, 10, 2, 20, 0, tzinfo=TZ)
    assert split_by_day(start, start + timedelta(minutes=30)) == [(start.date(), 1800)]


def test_split_by_day_over_midnight():
    start = datetime(2026, 10, 2, 23, 30, tzinfo=TZ)
    parts = split_by_day(start, start + timedelta(hours=1))
    assert parts == [(start.date(), 1800), (start.date() + timedelta(days=1), 1800)]


async def test_flush_and_summaries(db_session):
    buffer = StatsBuffer()
    buffer.guild_names[1] = "Wikinger"
    day = today()
    for _ in range(3):
        buffer.message(1, 100, day)
    buffer.message(1, 200, day)
    buffer.join(1, day)
    buffer.join(1, day)
    buffer.leave(1, day)
    start = datetime.combine(day, datetime.min.time(), tzinfo=TZ) + timedelta(hours=1)
    buffer.voice(1, 200, start, start + timedelta(minutes=90))
    await flush(buffer)

    # zweiter Flush addiert, statt zu ueberschreiben
    buffer.message(1, 100, day)
    await flush(buffer)

    data = await server_summary(1, 7)
    assert (data["joins"], data["leaves"], data["messages"], data["voice_seconds"]) == (2, 1, 5, 5400)
    assert data["top_messages"] == [(100, 4), (200, 1)]
    assert data["top_voice"] == [(200, 5400)]
    assert data["busiest_day"] == (day, 5)

    assert await member_summary(1, 100, 30) == {"messages": 4, "voice_seconds": 0, "rank": 1}
    assert (await member_summary(1, 200, 30))["rank"] == 2
    assert (await member_summary(1, 999, 30))["rank"] is None


async def test_purge_removes_only_old_member_rows(db_session):
    buffer = StatsBuffer()
    buffer.message(1, 100, today())
    buffer.message(1, 100, today() - timedelta(days=200))
    await flush(buffer)

    assert await purge_member_rows(90) == 1
    rows = (await db_session.execute(StatsMemberDaily.__table__.select())).all()
    assert len(rows) == 1


def test_format_duration():
    assert format_duration(59) == "0 min"
    assert format_duration(5400) == "1 h 30 min"


def test_counter_name():
    guild = SimpleNamespace(members=[SimpleNamespace(bot=False)] * 3 + [SimpleNamespace(bot=True)], member_count=4)
    assert counter_name("👥 Mitglieder: {count}", guild) == "👥 Mitglieder: 3"
    assert counter_name("{all} gesamt", guild) == "4 gesamt"
