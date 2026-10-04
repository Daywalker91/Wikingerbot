"""Einstellungen: Cogs aus der Oberflaeche laden/entladen (nur im Bot-Prozess)."""

from types import SimpleNamespace

import httpx

from api.main import app
from api.middleware.auth import create_access_token
from bot.core import runtime
from db.models.role import Level


async def _client(level=Level.OWNER):
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    client.cookies.set("session", create_access_token(100, 1, level))
    return client


async def test_change_cog(monkeypatch):
    calls = []

    async def load(name):
        calls.append(("load", name))

    async def unload(name):
        calls.append(("unload", name))

    async def reload(name):
        raise RuntimeError("Syntaxfehler in cog.py\ndetails")

    async with await _client() as client:
        monkeypatch.setattr(runtime, "bot", None)
        assert (await client.post("/admin/cogs/music/unload")).status_code == 503

        monkeypatch.setattr(runtime, "bot", SimpleNamespace(load_cog=load, unload_cog=unload, reload_cog=reload))
        assert (await client.post("/admin/cogs/music/unload")).status_code == 200
        assert (await client.post("/admin/cogs/music/load")).status_code == 200
        assert (await client.post("/admin/cogs/admin/unload")).status_code == 400  # geschuetzt
        assert (await client.post("/admin/cogs/gibtsnicht/load")).status_code == 404
        failed = await client.post("/admin/cogs/music/reload")
        assert failed.status_code == 400 and failed.json()["detail"] == "Fehlgeschlagen: Syntaxfehler in cog.py"
    assert calls == [("unload", "music"), ("load", "music")]

    async with await _client(Level.ADMIN) as client:
        assert (await client.post("/admin/cogs/music/unload")).status_code == 403
