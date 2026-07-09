from unittest.mock import AsyncMock, patch

import httpx
import pytest

from bot.core import steam_art
from bot.core.steam_art import fetch_header_image, parse_steam_appid


def test_parse_steam_appid_extracts_id_from_steam_prefix():
    assert parse_steam_appid("steam:1326470") == 1326470


def test_parse_steam_appid_returns_none_for_non_steam_source():
    assert parse_steam_appid("minecraft") is None
    assert parse_steam_appid("generic:some-module") is None


async def test_fetch_header_image_uses_cache_without_http_call(tmp_path, monkeypatch):
    monkeypatch.setattr(steam_art, "CACHE_DIR", tmp_path)
    cached_file = tmp_path / "123.jpg"
    cached_file.write_bytes(b"fake-image-bytes")

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        result = await fetch_header_image(123)

    mock_get.assert_not_called()
    assert result == cached_file


async def test_fetch_header_image_downloads_and_caches_on_success(tmp_path, monkeypatch):
    monkeypatch.setattr(steam_art, "CACHE_DIR", tmp_path)
    response = httpx.Response(200, content=b"downloaded-bytes")

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=response):
        result = await fetch_header_image(456)

    assert result == tmp_path / "456.jpg"
    assert result.read_bytes() == b"downloaded-bytes"


async def test_fetch_header_image_returns_none_on_non_200(tmp_path, monkeypatch):
    monkeypatch.setattr(steam_art, "CACHE_DIR", tmp_path)
    response = httpx.Response(404)

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=response):
        result = await fetch_header_image(789)

    assert result is None
    assert not (tmp_path / "789.jpg").exists()


async def test_fetch_header_image_returns_none_on_network_error(tmp_path, monkeypatch):
    monkeypatch.setattr(steam_art, "CACHE_DIR", tmp_path)

    with patch(
        "httpx.AsyncClient.get", new_callable=AsyncMock, side_effect=httpx.ConnectError("no network")
    ):
        result = await fetch_header_image(999)

    assert result is None
