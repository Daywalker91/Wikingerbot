"""Verbindungsadresse: Host aus Eintrag/Standard/PUBLIC_URL, Port aus Eintrag oder AMP."""

from types import SimpleNamespace

from bot.core import server_address
from bot.core.config import settings
from bot.core.guild_config import set_config
from bot.core.server_address import connect_address, game_port, split_port
from db.models.guild import Guild

ENDPOINTS = [
    {"DisplayName": "SFTP Server", "Endpoint": "0.0.0.0:2224", "Uri": "sftp://0.0.0.0:2224"},
    {"DisplayName": "Application Address", "Endpoint": "0.0.0.0:7777", "Uri": "steam://connect/0.0.0.0:7777"},
]


def test_split_port():
    assert split_port("spiel.example.org:2456") == ("spiel.example.org", 2456)
    assert split_port("spiel.example.org") == ("spiel.example.org", None)
    assert split_port("[2001:db8::1]:27015") == ("[2001:db8::1]", 27015)
    assert split_port("2001:db8::1") == ("2001:db8::1", None)  # IPv6 ohne Klammern: kein Port
    assert split_port("") == ("", None)


def test_game_port_prefers_application_address():
    assert game_port(ENDPOINTS) == 7777
    assert game_port([ENDPOINTS[0], {"DisplayName": "Game Port", "Endpoint": "0.0.0.0:2456"}]) == 2456
    assert game_port([ENDPOINTS[0]]) is None
    assert game_port([SimpleNamespace(DisplayName="Server", Endpoint="1.2.3.4:25565", Uri="")]) == 25565
    assert game_port([]) is None


def server(host, instance="abc"):
    return SimpleNamespace(host=host, guild_id=1, amp_instance_id=instance)


async def test_connect_address_combines_host_and_amp_port(db_session, monkeypatch):
    db_session.add(Guild(id=1, name="Wikinger"))
    await db_session.commit()
    monkeypatch.setattr(server_address, "_ports", {"abc": 7777})
    monkeypatch.setattr(settings, "public_url", "https://bot.example.org/")

    assert await connect_address(server("spiel.example.org")) == "spiel.example.org:7777"
    assert await connect_address(server("spiel.example.org:2456")) == "spiel.example.org:2456"  # eigener Port gilt
    assert await connect_address(server("", "unbekannt")) == "bot.example.org"  # ohne Port aus AMP

    assert await connect_address(server("")) == "bot.example.org:7777"  # Rueckfall PUBLIC_URL
    await set_config(1, "game_host", "spiel.example.org")
    assert await connect_address(server("")) == "spiel.example.org:7777"  # Standard-Spieladresse

    monkeypatch.setattr(settings, "public_url", "")
    await set_config(1, "game_host", "")
    assert await connect_address(server("")) == ""  # gar kein Host bekannt


async def test_instance_ports_reads_amp_and_caches(monkeypatch):
    calls = []

    async def list_instances():
        calls.append(1)
        return [SimpleNamespace(instance_id="abc", endpoints=ENDPOINTS), SimpleNamespace(instance_id="x", endpoints=[])]

    from bot.core.amp_client import amp_client

    monkeypatch.setattr(amp_client, "list_instances", list_instances)
    server_address.clear_cache()
    assert await server_address.instance_ports() == {"abc": 7777}
    assert await server_address.instance_ports() == {"abc": 7777}
    assert calls == [1]  # zweiter Aufruf aus dem Zwischenspeicher
