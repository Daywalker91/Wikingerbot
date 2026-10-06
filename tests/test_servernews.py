"""Server-News: AMP-Zeitplan auswerten, Vorlaufzeiten, Ankuendigen -> Ausfuehren -> laeuft wieder, Ausfaelle."""

from datetime import datetime, timedelta
from types import SimpleNamespace

from bot.cogs.servernews import cog as servernews_cog
from bot.cogs.servernews.cog import ServerNewsCog
from bot.cogs.servernews.notices import create_notice, due_lead, load_settings, parse_leads, parse_start, utcnow
from bot.cogs.servernews.schedule import interrupting_triggers, next_run, planned_runs, task_kind
from bot.core.guild_config import set_config
from db.models.guild import Guild
from db.models.server import Server
from db.models.server_notice import ServerNotice
from db.session import get_db_session


def test_task_kinds():
    assert task_kind("Core.RestartApplication") == "restart"
    assert task_kind("Core.UpdateApplication") == "update"
    assert task_kind("Core.StopApplication") == "stop"
    assert task_kind("Core.SendConsoleMessage") is None and task_kind("LocalFileBackup.TakeBackup") is None


def test_next_run_daily_and_weekday():
    wed_2330 = datetime(2026, 10, 7, 23, 30)  # Mittwoch
    daily_5 = {"MatchMinutes": [0], "MatchHours": [5]}
    assert next_run(daily_5, wed_2330) == datetime(2026, 10, 8, 5, 0)
    sunday_4 = {"MatchMinutes": [0], "MatchHours": [4], "MatchDays": [0]}  # .NET: 0 = Sonntag
    assert next_run(sunday_4, wed_2330) == datetime(2026, 10, 11, 4, 0)
    every_6h = {"MatchMinutes": [30], "MatchHours": [0, 6, 12, 18]}
    assert next_run(every_6h, wed_2330) == datetime(2026, 10, 8, 0, 30)
    assert next_run({"MatchMonths": [2], "MatchMinutes": [0], "MatchHours": [1]}, wed_2330) is None  # ausserhalb 8 Tage


async def test_planned_runs_from_amp_schedule():
    schedule = {
        "PopulatedTriggers": [
            {"Id": "t1", "Description": "Every day at 05:00", "EnabledState": 1,
             "Tasks": [{"TaskMethodName": "Core.SendConsoleMessage", "EnabledState": 1}, {"TaskMethodName": "Core.RestartApplication", "EnabledState": 1}]},
            {"Id": "t2", "Description": "Update available", "EnabledState": 1, "Tasks": [{"TaskMethodName": "Core.UpdateApplication"}]},
            {"Id": "t3", "Description": "Backup", "EnabledState": 1, "Tasks": [{"TaskMethodName": "LocalFileBackup.TakeBackup"}]},
            {"Id": "t4", "Description": "aus", "EnabledState": 0, "Tasks": [{"TaskMethodName": "Core.RestartApplication"}]},
        ]
    }
    assert [t[:2] for t in interrupting_triggers(schedule)] == [("t1", "restart"), ("t2", "update")]

    async def call(instance_id, endpoint, args):
        if endpoint == "GetScheduleData":
            return schedule
        if args["Id"] == "t1":
            return {"MatchMinutes": [0], "MatchHours": [5]}
        raise RuntimeError("not a time trigger")  # Ereignis-Trigger

    runs = await planned_runs(call, "i1", datetime(2026, 10, 7, 12, 0))
    assert [(r.trigger_id, r.kind, r.at) for r in runs] == [("t1", "restart", datetime(2026, 10, 8, 5, 0))]


def test_leads_and_start():
    assert parse_leads("60, 15,5, 5, 9999") == [60, 15, 5]
    assert parse_leads("") == [30, 10, 1]
    at = parse_start("15")
    assert at is not None and abs((at - utcnow()).total_seconds() - 900) < 5
    assert parse_start("25:00") is None and parse_start("abc") is None and parse_start("20:00") is not None


def test_due_lead_late_announcement_sends_once():
    now = utcnow()
    notice = ServerNotice(at=now + timedelta(minutes=12), sent_leads="[]")
    lead, sent = due_lead(notice, [30, 10, 1], now)
    assert lead == 30 and sent == [30]  # eine Meldung statt drei
    notice.sent_leads = "[30]"
    assert due_lead(notice, [30, 10, 1], now)[0] is None
    lead, sent = due_lead(notice, [30, 10, 1], now + timedelta(minutes=3))
    assert lead == 10 and sent == [30, 10]


class FakeChannel:
    def __init__(self):
        self.sent = []
        self.guild = SimpleNamespace(get_role=lambda rid: SimpleNamespace(id=rid, mention=f"<@&{rid}>"))

    async def send(self, content, allowed_mentions=None):
        self.sent.append(content)


async def test_restart_flow_and_outage(db_session, monkeypatch):
    db_session.add(Guild(id=1, name="Wikinger"))
    await db_session.commit()
    db_session.add(Server(guild_id=1, instance_name="valheim", amp_instance_id="i1", display_name="Valheim", host=""))
    await db_session.commit()
    await set_config(1, "servernews_channel_id", "500", "Wikinger")
    await set_config(1, "servernews_ping_role_id", "77", "Wikinger")
    await set_config(1, "servernews_ingame", '{"1": "say {text}"}', "Wikinger")

    state = {"up": True}
    calls = []

    async def is_up(server):
        return state["up"]

    class FakeAMP:
        async def instance_core_call(self, iid, endpoint, args):
            calls.append(endpoint)

        async def send_console_message(self, iid, message):
            calls.append(message)

        async def stop(self, iid):
            calls.append("stop")

    async def address(server):
        return "wikinger.example:2456"

    monkeypatch.setattr(servernews_cog, "_is_up", is_up)
    monkeypatch.setattr(servernews_cog, "amp_client", FakeAMP())
    monkeypatch.setattr(servernews_cog, "connect_address", address)
    channel = FakeChannel()
    guild = SimpleNamespace(id=1, name="Wikinger", get_channel=lambda cid: channel if cid == 500 else None)
    cog = ServerNewsCog(SimpleNamespace(guilds=[guild]))

    async with get_db_session() as db:
        server = (await db.get(Server, 1))
    notice = await create_notice(1, server.id, "restart", utcnow() + timedelta(minutes=20), reason="Mod-Update")
    settings = await load_settings(1)

    await cog.run_guild(guild)  # erste Meldung mit Ping, Hinweis im Spiel
    assert "Valheim" in channel.sent[0] and "Mod-Update" in channel.sent[0] and "<@&77>" in channel.sent[0]
    assert any(c.startswith("say [Server] Neustart in 20") or c.startswith("say [Server] Neustart in 19") for c in calls)

    # Zeit erreicht: Bot startet neu, Meldung, Server unten -> keine "Ausfall"-Meldung
    async with get_db_session() as db:
        row = await db.get(ServerNotice, notice.id)
        row.at = utcnow() - timedelta(seconds=5)
        await db.commit()
    state["up"] = False
    await cog.run_guild(guild)
    assert "RestartApplication" in calls and "startet jetzt neu" in channel.sent[-1]
    assert not any("nicht angekündigt" in m for m in channel.sent)

    # wieder da
    async with get_db_session() as db:
        row = await db.get(ServerNotice, notice.id)
        row.at = utcnow() - timedelta(minutes=3)
        await db.commit()
    state["up"] = True
    await cog.run_guild(guild)
    assert "läuft wieder" in channel.sent[-1] and "wikinger.example:2456" in channel.sent[-1]
    async with get_db_session() as db:
        assert (await db.get(ServerNotice, notice.id)).status == "done"

    # unangekuendigter Ausfall: gemeldet ohne Ping, dann wieder da
    count = len(channel.sent)
    state["up"] = False
    await cog.run_guild(guild)
    assert "nicht angekündigt" in channel.sent[count] and "<@&77>" not in channel.sent[count]
    state["up"] = True
    await cog.run_guild(guild)
    assert "läuft wieder" in channel.sent[-1]
    assert settings.leads == [30, 10, 1]
