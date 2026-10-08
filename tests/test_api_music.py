"""Musik-API (bot/cogs/music/api.py) mit nachgebautem Bot - ohne Discord."""

from types import SimpleNamespace

import httpx

from api.main import app
from api.middleware.auth import create_access_token
from bot.cogs.music import api as music_api
from bot.cogs.music.player import Track
from bot.core import runtime
from db.models.guild import Guild
from db.models.role import Level


class FakeCog:
    def __init__(self):
        self.started = []
        self.controls = []

    def state(self, guild):
        return {"connected": False, "channel_id": None, "channel_name": None, "paused": False, "current": None,
                "queue": [], "queue_length": 0, "volume": 50}

    async def resolve_tracks(self, guild_id, kind, name, user_id, *, episode=0, shuffle=False):
        return [Track(name, "x", "stream", user_id, kind)]

    async def start_tracks(self, guild, channel, tracks):
        self.started.append((channel, tracks))
        return len(tracks)

    async def control(self, guild, action, value=None):
        self.controls.append((action, value))


def fake_bot(cog, *, in_voice: bool):
    channel = SimpleNamespace(id=555, name="Taverne")
    member = SimpleNamespace(voice=SimpleNamespace(channel=channel) if in_voice else None)
    guild = SimpleNamespace(
        id=1,
        name="Wikinger",
        voice_client=None,
        text_channels=[SimpleNamespace(id=1523404561895784448, name="allgemein")],
        get_member=lambda user_id: member,
    )
    return SimpleNamespace(get_cog=lambda name: cog if name == "MusicCog" else None, get_guild=lambda gid: guild), channel


async def _client(level: Level) -> httpx.AsyncClient:
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    client.cookies.set("session", create_access_token(100, 1, level))
    return client


async def test_without_bot_process_explains(monkeypatch):
    monkeypatch.setattr(runtime, "bot", None)
    async with await _client(Level.MEMBER) as client:
        response = await client.get("/music/state")
    assert response.status_code == 503 and "im Bot" in response.json()["detail"]


async def test_play_requires_voice_channel(monkeypatch):
    bot, _ = fake_bot(FakeCog(), in_voice=False)
    monkeypatch.setattr(runtime, "bot", bot)
    async with await _client(Level.MEMBER) as client:
        response = await client.post("/music/play", json={"kind": "radio", "name": "FIP"})
    assert response.status_code == 400 and "Voice-Kanal" in response.json()["detail"]


async def test_play_goes_to_callers_channel(monkeypatch):
    cog = FakeCog()
    bot, channel = fake_bot(cog, in_voice=True)
    monkeypatch.setattr(runtime, "bot", bot)
    async with await _client(Level.MEMBER) as client:
        response = await client.post("/music/play", json={"kind": "radio", "name": "FIP"})
    assert response.json() == {"added": 1}
    assert cog.started[0][0] is channel


async def test_control_needs_same_channel_or_mod(monkeypatch):
    cog = FakeCog()
    bot, _ = fake_bot(cog, in_voice=False)
    monkeypatch.setattr(runtime, "bot", bot)
    async with await _client(Level.MEMBER) as client:
        assert (await client.post("/music/control", json={"action": "skip"})).status_code == 403
    async with await _client(Level.MOD) as client:
        assert (await client.post("/music/control", json={"action": "volume", "value": 30})).status_code == 200
    assert cog.controls == [("volume", 30)]


async def test_invalid_input_rejected(monkeypatch):
    bot, _ = fake_bot(FakeCog(), in_voice=True)
    monkeypatch.setattr(runtime, "bot", bot)
    async with await _client(Level.MOD) as client:
        assert (await client.post("/music/play", json={"kind": "youtube", "name": "x"})).status_code == 422
        assert (await client.post("/music/control", json={"action": "volume", "value": 500})).status_code == 422


async def test_admin_config_and_ids_as_text(db_session, monkeypatch):
    db_session.add(Guild(id=1, name="Wikinger"))
    await db_session.commit()
    bot, _ = fake_bot(FakeCog(), in_voice=True)
    monkeypatch.setattr(runtime, "bot", bot)

    async with await _client(Level.MEMBER) as client:
        assert (await client.get("/music/config")).status_code == 403

    async with await _client(Level.ADMIN) as client:
        assert (await client.post("/music/stations", json={"name": "FIP", "url": "https://icecast.radiofrance.fr/fip-midfi.mp3"})).status_code == 200
        assert (await client.post("/music/stations", json={"name": "X", "url": "file:///etc/passwd"})).status_code == 422
        config = (await client.get("/music/config")).json()
        library = (await client.get("/music/library")).json()

    assert config["stations"] == [{"name": "FIP", "category": "", "url": "https://icecast.radiofrance.fr/fip-midfi.mp3"}]
    assert config["text_channels"] == [{"id": "1523404561895784448", "name": "allgemein"}]  # als Text, nicht gerundet
    assert library["stations"] == [{"name": "FIP", "category": ""}]


async def test_announce_stores_exact_channel_id(db_session, monkeypatch):
    db_session.add(Guild(id=1, name="Wikinger"))
    await db_session.commit()
    bot, _ = fake_bot(FakeCog(), in_voice=True)
    monkeypatch.setattr(runtime, "bot", bot)
    await music_api._save_json(1, "podcast_feeds", {"Funk": {"url": "https://example.org/feed", "channel_id": None}})

    async with await _client(Level.ADMIN) as client:
        response = await client.put("/music/podcasts/Funk/announce", json={"channel_id": "1523404561895784448"})
        config = (await client.get("/music/config")).json()

    assert response.status_code == 200
    assert config["podcasts"][0]["channel_id"] == "1523404561895784448"


async def test_station_categories_and_bulk(db_session, monkeypatch):
    db_session.add(Guild(id=1, name="Wikinger"))
    await db_session.commit()
    bot, _ = fake_bot(FakeCog(), in_voice=True)
    monkeypatch.setattr(runtime, "bot", bot)

    async with await _client(Level.ADMIN) as client:
        await client.post("/music/stations", json={"name": "Rock Antenne", "url": "https://rock.example/a", "category": "Rock"})
        await client.post("/music/stations", json={"name": "Bob", "url": "https://bob.example/b", "category": "rock"})  # Schreibweise uebernommen
        await client.post("/music/stations", json={"name": "Jazz FM", "url": "https://jazz.example/j"})
        config = (await client.get("/music/config")).json()
        assert {s["name"]: s["category"] for s in config["stations"]} == {"Bob": "Rock", "Jazz FM": "", "Rock Antenne": "Rock"}

        moved = (await client.post("/music/stations/bulk", json={"names": ["Jazz FM", "Bob"], "action": "category", "category": "Mix"})).json()
        assert moved["message"] == "2 Sender in „Mix“ verschoben."
        deleted = (await client.post("/music/stations/bulk", json={"names": ["Bob"], "action": "delete"})).json()
        assert deleted["message"] == "1 Sender entfernt."
        library = (await client.get("/music/library")).json()

    assert library["stations"] == [{"name": "Jazz FM", "category": "Mix"}, {"name": "Rock Antenne", "category": "Rock"}]
    assert await music_api._json(1, "music_station_categories") == {"Rock Antenne": "Rock", "Jazz FM": "Mix"}  # Bob weg


async def test_rename_and_tidy_via_api(db_session, monkeypatch):
    db_session.add(Guild(id=1, name="Wikinger"))
    await db_session.commit()
    bot, _ = fake_bot(FakeCog(), in_voice=True)
    monkeypatch.setattr(runtime, "bot", bot)
    await music_api._save_json(1, "music_stations", {
        "program": "https://hls.somafm.com/hls/groovesalad/320k/program.m3u8",
        "Jazz": "https://jazz.example/live",
    })
    await music_api._save_json(1, "music_station_categories", {"Jazz": "Jazz"})

    async with await _client(Level.ADMIN) as client:
        tidy = (await client.post("/music/stations/tidy-names")).json()
        assert tidy["message"] == "1 Sender umbenannt."
        assert (await client.put("/music/stations/Jazz", json={"name": "Jazz Radio"})).status_code == 200
        conflict = await client.put("/music/stations/Jazz Radio", json={"name": "somafm groovesalad 320k"})
        assert conflict.status_code == 409
        assert (await client.put("/music/stations/Weg", json={"name": "x"})).status_code == 404
        library = (await client.get("/music/library")).json()

    assert library["stations"] == [{"name": "Jazz Radio", "category": "Jazz"}, {"name": "somafm groovesalad 320k", "category": ""}]
