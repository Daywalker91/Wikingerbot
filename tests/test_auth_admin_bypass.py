from unittest.mock import AsyncMock

import httpx

from api.routers.auth import (
    _has_administrator_permission,
    _has_owner_level_bypass,
    _is_guild_owner,
)

GUILD_ID = 1


def _client_returning(json_by_path: dict[str, object]) -> httpx.AsyncClient:
    client = AsyncMock(spec=httpx.AsyncClient)

    async def _get(url: str, **kwargs):
        for path, payload in json_by_path.items():
            if url.endswith(path):
                request = httpx.Request("GET", url)
                return httpx.Response(200, json=payload, request=request)
        raise AssertionError(f"Unerwarteter Request an {url}")

    client.get = AsyncMock(side_effect=_get)
    return client


def _erroring_client() -> httpx.AsyncClient:
    client = AsyncMock(spec=httpx.AsyncClient)
    client.get = AsyncMock(side_effect=httpx.ConnectError("kein Netz"))
    return client


async def test_administrator_role_grants_bypass():
    roles = [{"id": str(GUILD_ID), "permissions": "0"}, {"id": "42", "permissions": "8"}]
    client = _client_returning({"/roles": roles})

    assert await _has_administrator_permission(client, GUILD_ID, [42]) is True


async def test_non_administrator_roles_do_not_grant_bypass():
    roles = [{"id": str(GUILD_ID), "permissions": "0"}, {"id": "42", "permissions": "2048"}]
    client = _client_returning({"/roles": roles})

    assert await _has_administrator_permission(client, GUILD_ID, [42]) is False


async def test_everyone_role_administrator_counts_too():
    # @everyone-Rolle hat dieselbe ID wie die Guild selbst - zaehlt immer mit,
    # auch wenn sie nicht explizit in den Member-Rollen aufgefuehrt ist.
    roles = [{"id": str(GUILD_ID), "permissions": "8"}]
    client = _client_returning({"/roles": roles})

    assert await _has_administrator_permission(client, GUILD_ID, []) is True


async def test_discord_api_error_fails_closed_without_bypass():
    client = _erroring_client()

    assert await _has_administrator_permission(client, GUILD_ID, [42]) is False


async def test_guild_owner_is_recognized():
    client = _client_returning({f"/guilds/{GUILD_ID}": {"owner_id": "999"}})

    assert await _is_guild_owner(client, GUILD_ID, 999) is True
    assert await _is_guild_owner(client, GUILD_ID, 111) is False


async def test_guild_owner_lookup_error_fails_closed():
    client = _erroring_client()

    assert await _is_guild_owner(client, GUILD_ID, 999) is False


async def test_owner_level_bypass_true_for_owner_without_administrator_role():
    # Genau der Fall, der live aufgefallen ist: Server-Owner ohne eigene Rolle
    # mit Administrator-Recht (nur @everyone + eine gemanagte Bot-Rolle).
    client = _client_returning(
        {
            f"/guilds/{GUILD_ID}": {"owner_id": "999"},
            "/roles": [{"id": str(GUILD_ID), "permissions": "104320577"}],
        }
    )

    assert await _has_owner_level_bypass(client, GUILD_ID, 999, []) is True


async def test_owner_level_bypass_false_for_regular_member():
    client = _client_returning(
        {
            f"/guilds/{GUILD_ID}": {"owner_id": "999"},
            "/roles": [{"id": str(GUILD_ID), "permissions": "0"}],
        }
    )

    assert await _has_owner_level_bypass(client, GUILD_ID, 111, []) is False
