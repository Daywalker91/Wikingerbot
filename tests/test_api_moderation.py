import httpx
from sqlalchemy import select

from api.main import app
from api.middleware.auth import create_access_token
from db.models.guild import Guild
from db.models.modlog import ModAction, ModLogEntry, Warning, WarnEscalationState
from db.models.role import Level
from db.models.user import User


async def _client() -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


def _cookie_for(user_id: int, guild_id: int, level: Level) -> str:
    return create_access_token(user_id, guild_id, level)


async def _seed_guild_and_user(db_session, *, guild_id: int = 1, user_id: int = 200):
    db_session.add(Guild(id=guild_id, name="Wikinger"))
    db_session.add(User(id=user_id, username="Bösewicht"))
    await db_session.commit()


class _FakeResponse:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


class _FakeAsyncClient:
    def __init__(self, delete_status: int = 204, put_status: int = 204) -> None:
        self.delete_status = delete_status
        self.put_status = put_status
        self.delete_calls: list[tuple[str, dict]] = []
        self.put_calls: list[tuple[str, dict, dict]] = []

    async def __aenter__(self) -> "_FakeAsyncClient":
        return self

    async def __aexit__(self, *args) -> None:
        return None

    async def delete(self, url: str, headers: dict) -> _FakeResponse:
        self.delete_calls.append((url, headers))
        return _FakeResponse(self.delete_status)

    async def put(self, url: str, headers: dict, json: dict) -> _FakeResponse:
        self.put_calls.append((url, headers, json))
        return _FakeResponse(self.put_status)


async def test_list_modlog_without_cookie_is_unauthorized():
    async with await _client() as client:
        response = await client.get("/moderation/modlog")

    assert response.status_code == 401


async def test_list_modlog_requires_at_least_mod():
    async with await _client() as client:
        client.cookies.set("session", _cookie_for(100, 1, Level.MEMBER))
        response = await client.get("/moderation/modlog")

    assert response.status_code == 403


async def test_list_modlog_returns_entries_for_own_guild(db_session):
    await _seed_guild_and_user(db_session)
    db_session.add(
        ModLogEntry(guild_id=1, user_id=200, mod_id=100, action=ModAction.KICK, reason="Stoerung")
    )
    db_session.add(
        ModLogEntry(guild_id=2, user_id=200, mod_id=100, action=ModAction.KICK, reason="Andere Guild")
    )
    await db_session.commit()

    async with await _client() as client:
        client.cookies.set("session", _cookie_for(100, 1, Level.MOD))
        response = await client.get("/moderation/modlog")

    assert response.status_code == 200
    [entry] = response.json()
    assert entry["action"] == "kick"
    assert entry["reason"] == "Stoerung"


async def test_list_warnings_filters_expired_by_default(db_session):
    await _seed_guild_and_user(db_session)
    db_session.add(Warning(guild_id=1, user_id=200, mod_id=100, reason="aktiv", points=1, expired=False))
    db_session.add(Warning(guild_id=1, user_id=200, mod_id=100, reason="abgelaufen", points=1, expired=True))
    await db_session.commit()

    async with await _client() as client:
        client.cookies.set("session", _cookie_for(100, 1, Level.MOD))
        active = await client.get("/moderation/warnings")
        all_warnings = await client.get("/moderation/warnings", params={"active_only": "false"})

    assert len(active.json()) == 1
    assert active.json()[0]["reason"] == "aktiv"
    assert len(all_warnings.json()) == 2


async def test_unban_calls_discord_and_writes_modlog(db_session, monkeypatch):
    await _seed_guild_and_user(db_session)
    # httpx.AsyncClient() muss erst NACH dem Erzeugen des Test-Clients gepatcht
    # werden - "bot.cogs.moderation.api.httpx" ist dasselbe Modulobjekt wie das
    # global importierte httpx, ein frueheres Patchen wuerde auch den ASGI-
    # Testclient-Konstruktor oben treffen.
    test_client = await _client()
    fake_client = _FakeAsyncClient(delete_status=204)
    monkeypatch.setattr("bot.cogs.moderation.api.httpx.AsyncClient", lambda: fake_client)

    async with test_client as client:
        client.cookies.set("session", _cookie_for(100, 1, Level.MOD))
        response = await client.post(
            "/moderation/unban", json={"user_id": 200, "reason": "Bewaehrung"}
        )

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert fake_client.delete_calls[0][0] == "https://discord.com/api/guilds/1/bans/200"

    result = await db_session.execute(
        select(ModLogEntry).where(ModLogEntry.action == ModAction.UNBAN)
    )
    [entry] = result.scalars().all()
    assert entry.user_id == 200
    assert entry.mod_id == 100


async def test_unban_treats_not_banned_as_success(db_session, monkeypatch):
    await _seed_guild_and_user(db_session)
    test_client = await _client()
    fake_client = _FakeAsyncClient(delete_status=404)
    monkeypatch.setattr("bot.cogs.moderation.api.httpx.AsyncClient", lambda: fake_client)

    async with test_client as client:
        client.cookies.set("session", _cookie_for(100, 1, Level.MOD))
        response = await client.post(
            "/moderation/unban", json={"user_id": 200, "reason": "War nie gebannt"}
        )

    assert response.status_code == 200


async def test_unban_fails_on_discord_error(db_session, monkeypatch):
    await _seed_guild_and_user(db_session)
    test_client = await _client()
    fake_client = _FakeAsyncClient(delete_status=500)
    monkeypatch.setattr("bot.cogs.moderation.api.httpx.AsyncClient", lambda: fake_client)

    async with test_client as client:
        client.cookies.set("session", _cookie_for(100, 1, Level.MOD))
        response = await client.post(
            "/moderation/unban", json={"user_id": 200, "reason": "Egal"}
        )

    assert response.status_code == 502


async def test_ban_calls_discord_and_writes_modlog(db_session, monkeypatch):
    await _seed_guild_and_user(db_session)
    test_client = await _client()
    fake_client = _FakeAsyncClient(put_status=204)
    monkeypatch.setattr("bot.cogs.moderation.api.httpx.AsyncClient", lambda: fake_client)

    async with test_client as client:
        client.cookies.set("session", _cookie_for(100, 1, Level.MOD))
        response = await client.post(
            "/moderation/ban",
            json={"user_id": 200, "reason": "Spam", "delete_message_days": 1},
        )

    assert response.status_code == 200
    assert response.json()["ok"] is True
    url, _headers, json_body = fake_client.put_calls[0]
    assert url == "https://discord.com/api/guilds/1/bans/200"
    assert json_body == {"delete_message_seconds": 86400}

    result = await db_session.execute(select(ModLogEntry).where(ModLogEntry.action == ModAction.BAN))
    [entry] = result.scalars().all()
    assert entry.user_id == 200
    assert entry.mod_id == 100
    assert entry.reason == "Spam"


async def test_ban_requires_at_least_mod(db_session):
    await _seed_guild_and_user(db_session)

    async with await _client() as client:
        client.cookies.set("session", _cookie_for(100, 1, Level.MEMBER))
        response = await client.post(
            "/moderation/ban", json={"user_id": 200, "reason": "Spam", "delete_message_days": 0}
        )

    assert response.status_code == 403


async def test_ban_fails_on_discord_error(db_session, monkeypatch):
    await _seed_guild_and_user(db_session)
    test_client = await _client()
    fake_client = _FakeAsyncClient(put_status=500)
    monkeypatch.setattr("bot.cogs.moderation.api.httpx.AsyncClient", lambda: fake_client)

    async with test_client as client:
        client.cookies.set("session", _cookie_for(100, 1, Level.MOD))
        response = await client.post(
            "/moderation/ban", json={"user_id": 200, "reason": "Spam", "delete_message_days": 0}
        )

    assert response.status_code == 502


async def test_get_mod_config_returns_defaults(db_session):
    await _seed_guild_and_user(db_session)

    async with await _client() as client:
        client.cookies.set("session", _cookie_for(100, 1, Level.OWNER))
        response = await client.get("/moderation/mod-config")

    assert response.status_code == 200
    assert response.json() == {
        "warn_threshold": 3,
        "warn_ladder": ["timeout", "kick", "ban"],
        "warn_timeout_minutes": 60,
        "warn_decay_days": 30,
        "automod_warn_enabled": False,
        "automod_warn_points": {
            "spam": 1,
            "keyword": 2,
            "keyword_preset": 2,
            "mention_spam": 2,
            "harmful_link": 3,
            "member_profile": 1,
        },
        "automod_alert_channel_id": None,
    }


async def test_get_mod_config_requires_owner(db_session):
    await _seed_guild_and_user(db_session)

    async with await _client() as client:
        client.cookies.set("session", _cookie_for(100, 1, Level.MOD))
        response = await client.get("/moderation/mod-config")

    assert response.status_code == 403


async def test_update_mod_config_persists_values(db_session):
    await _seed_guild_and_user(db_session)

    async with await _client() as client:
        client.cookies.set("session", _cookie_for(100, 1, Level.OWNER))
        put_response = await client.put(
            "/moderation/mod-config",
            json={
                "warn_threshold": 5,
                "warn_ladder": ["ban", "kick"],
                "warn_timeout_minutes": 30,
                "warn_decay_days": 14,
                "automod_warn_enabled": True,
                "automod_warn_points": {
                    "spam": 2,
                    "keyword": 3,
                    "keyword_preset": 3,
                    "mention_spam": 3,
                    "harmful_link": 5,
                    "member_profile": 2,
                },
                "automod_alert_channel_id": 555,
            },
        )
        get_response = await client.get("/moderation/mod-config")

    assert put_response.status_code == 200
    assert get_response.json() == {
        "warn_threshold": 5,
        "warn_ladder": ["ban", "kick"],
        "warn_timeout_minutes": 30,
        "warn_decay_days": 14,
        "automod_warn_enabled": True,
        "automod_warn_points": {
            "spam": 2,
            "keyword": 3,
            "keyword_preset": 3,
            "mention_spam": 3,
            "harmful_link": 5,
            "member_profile": 2,
        },
        "automod_alert_channel_id": "555",
    }


class _FakeMemberSearchClient:
    def __init__(self, status_code: int = 200, members=None) -> None:
        self.status_code = status_code
        self.members = members if members is not None else []

    async def __aenter__(self) -> "_FakeMemberSearchClient":
        return self

    async def __aexit__(self, *args) -> None:
        return None

    async def get(self, url: str, headers: dict, params: dict):
        return httpx.Response(self.status_code, json=self.members, request=httpx.Request("GET", url))


async def test_search_members_returns_mapped_results(db_session, monkeypatch):
    await _seed_guild_and_user(db_session)
    test_client = await _client()
    members = [
        {"nick": "Der Böse", "user": {"id": "999", "username": "baddude", "global_name": "Bad Dude"}},
        {"nick": None, "user": {"id": "1000", "username": "goodie", "global_name": None}},
    ]
    fake = _FakeMemberSearchClient(members=members)
    monkeypatch.setattr("bot.cogs.moderation.api.httpx.AsyncClient", lambda: fake)

    async with test_client as client:
        client.cookies.set("session", _cookie_for(100, 1, Level.MOD))
        response = await client.get("/moderation/member-search", params={"query": "bad"})

    assert response.status_code == 200
    assert response.json() == [
        {"id": "999", "username": "baddude", "display_name": "Der Böse"},
        {"id": "1000", "username": "goodie", "display_name": "goodie"},
    ]


async def test_search_members_returns_empty_on_discord_error(db_session, monkeypatch):
    await _seed_guild_and_user(db_session)
    test_client = await _client()
    fake = _FakeMemberSearchClient(status_code=500)
    monkeypatch.setattr("bot.cogs.moderation.api.httpx.AsyncClient", lambda: fake)

    async with test_client as client:
        client.cookies.set("session", _cookie_for(100, 1, Level.MOD))
        response = await client.get("/moderation/member-search", params={"query": "bad"})

    assert response.status_code == 200
    assert response.json() == []


async def test_search_members_requires_at_least_mod(db_session):
    await _seed_guild_and_user(db_session)

    async with await _client() as client:
        client.cookies.set("session", _cookie_for(100, 1, Level.MEMBER))
        response = await client.get("/moderation/member-search", params={"query": "bad"})

    assert response.status_code == 403


async def test_list_escalations_returns_only_active_tiers(db_session):
    await _seed_guild_and_user(db_session)
    db_session.add(WarnEscalationState(guild_id=1, user_id=200, tier=2))
    db_session.add(WarnEscalationState(guild_id=1, user_id=201, tier=0))
    await db_session.commit()

    async with await _client() as client:
        client.cookies.set("session", _cookie_for(100, 1, Level.MOD))
        response = await client.get("/moderation/escalations")

    assert response.status_code == 200
    assert response.json() == [{"user_id": "200", "tier": 2}]


async def test_list_escalations_scoped_to_guild(db_session):
    await _seed_guild_and_user(db_session)
    db_session.add(Guild(id=2, name="Andere Guild"))
    db_session.add(WarnEscalationState(guild_id=2, user_id=200, tier=1))
    await db_session.commit()

    async with await _client() as client:
        client.cookies.set("session", _cookie_for(100, 1, Level.MOD))
        response = await client.get("/moderation/escalations")

    assert response.json() == []


async def test_reset_escalation_sets_tier_to_zero(db_session):
    await _seed_guild_and_user(db_session)
    db_session.add(WarnEscalationState(guild_id=1, user_id=200, tier=2))
    await db_session.commit()

    async with await _client() as client:
        client.cookies.set("session", _cookie_for(100, 1, Level.MOD))
        response = await client.post("/moderation/escalations/reset", json={"user_id": 200})

    assert response.status_code == 200
    state = await db_session.get(WarnEscalationState, (1, 200))
    assert state.tier == 0


async def test_reset_escalation_requires_at_least_mod(db_session):
    await _seed_guild_and_user(db_session)

    async with await _client() as client:
        client.cookies.set("session", _cookie_for(100, 1, Level.MEMBER))
        response = await client.post("/moderation/escalations/reset", json={"user_id": 200})

    assert response.status_code == 403


class _FakeChannelsClient:
    def __init__(self, status_code: int = 200, channels=None) -> None:
        self.status_code = status_code
        self.channels = channels if channels is not None else []

    async def __aenter__(self) -> "_FakeChannelsClient":
        return self

    async def __aexit__(self, *args) -> None:
        return None

    async def get(self, url: str, headers: dict):
        return httpx.Response(self.status_code, json=self.channels, request=httpx.Request("GET", url))


async def test_list_text_channels_filters_to_text_type(db_session, monkeypatch):
    await _seed_guild_and_user(db_session)
    test_client = await _client()
    channels = [
        {"id": "10", "name": "allgemein", "type": 0},
        {"id": "11", "name": "Sprachkanal", "type": 2},
        {"id": "12", "name": "mod-log", "type": 0},
    ]
    fake = _FakeChannelsClient(channels=channels)
    monkeypatch.setattr("bot.cogs.moderation.api.httpx.AsyncClient", lambda: fake)

    async with test_client as client:
        client.cookies.set("session", _cookie_for(100, 1, Level.OWNER))
        response = await client.get("/moderation/text-channels")

    assert response.status_code == 200
    assert response.json() == [
        {"id": "10", "name": "allgemein"},
        {"id": "12", "name": "mod-log"},
    ]


async def test_list_text_channels_requires_owner(db_session):
    await _seed_guild_and_user(db_session)

    async with await _client() as client:
        client.cookies.set("session", _cookie_for(100, 1, Level.MOD))
        response = await client.get("/moderation/text-channels")

    assert response.status_code == 403


async def test_list_text_channels_fails_on_discord_error(db_session, monkeypatch):
    await _seed_guild_and_user(db_session)
    test_client = await _client()
    fake = _FakeChannelsClient(status_code=500)
    monkeypatch.setattr("bot.cogs.moderation.api.httpx.AsyncClient", lambda: fake)

    async with test_client as client:
        client.cookies.set("session", _cookie_for(100, 1, Level.OWNER))
        response = await client.get("/moderation/text-channels")

    assert response.status_code == 502
