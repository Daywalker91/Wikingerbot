"""Banner-Tab: Einstellungen pro Server und Gruppe, Hintergrundbild, Vorschau."""

import io

import httpx
from PIL import Image

from api.main import app
from api.middleware.auth import create_access_token
from db.models.banner_group import BannerGroup
from db.models.guild import Guild
from db.models.role import Level
from db.models.server import BannerType, Server


async def _client(level=Level.OWNER, guild_id=1) -> httpx.AsyncClient:
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    client.cookies.set("session", create_access_token(100, guild_id, level))
    return client


async def seed(db_session):
    db_session.add_all([Guild(id=1, name="Wikinger"), Guild(id=2, name="Andere")])
    await db_session.commit()
    servers = [
        Server(guild_id=1, instance_name="ark", amp_instance_id="a", display_name="ARK", host="", steam_app_id=346110),
        Server(guild_id=1, instance_name="mc", amp_instance_id="m", display_name="Minecraft", host=""),
        Server(guild_id=2, instance_name="fremd", amp_instance_id="f", display_name="Fremd", host=""),
    ]
    db_session.add_all(servers)
    await db_session.commit()
    return [s.id for s in servers]


def png_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (40, 20), (200, 30, 30)).save(buffer, format="PNG")
    return buffer.getvalue()


async def test_owner_only_and_config_lists_own_servers(db_session):
    await seed(db_session)
    async with await _client(Level.ADMIN) as client:
        assert (await client.get("/banner/config")).status_code == 403
    async with await _client() as client:
        data = (await client.get("/banner/config")).json()
    assert [s["name"] for s in data["servers"]] == ["ARK", "Minecraft"]
    ark = data["servers"][0]
    assert ark["steam_art"] and ark["background"] == "steam"  # Steam-Artwork ist Standard
    assert data["servers"][1]["background"] == "theme" and data["cog_loaded"] is False


async def test_save_server_styles_and_rules(db_session):
    ark, mc, fremd = await seed(db_session)
    async with await _client() as client:
        # Aktivieren ohne Kanal geht nicht
        assert (await client.put(f"/banner/servers/{mc}", json={"enabled": True})).status_code == 400
        # Theme auf einem Steam-Spiel: Steam-Artwork wird abgeschaltet
        ok = await client.put(
            f"/banner/servers/{ark}",
            json={"enabled": True, "channel_id": "123456789012345678", "type": "image", "background": "theme", "theme": "forest", "blur": 5},
        )
        assert ok.status_code == 200 and "nicht geladen" in ok.json()["message"]
        # eigener Verlauf braucht beide Farben, Farben muessen #rrggbb sein
        bad = await client.put(f"/banner/servers/{mc}", json={"type": "image", "background": "colors", "color_start": "#ff0000"})
        assert bad.status_code == 400
        assert (await client.put(f"/banner/servers/{mc}", json={"background": "theme", "text_color": "rot"})).status_code == 422
        # Steam fuer Server ohne Steam-App, eigenes Bild ohne Upload, fremder Server
        assert (await client.put(f"/banner/servers/{mc}", json={"background": "steam"})).status_code == 400
        assert (await client.put(f"/banner/servers/{mc}", json={"background": "image"})).status_code == 400
        assert (await client.put(f"/banner/servers/{fremd}", json={"background": "theme"})).status_code == 404

    db_session.expire_all()
    server = await db_session.get(Server, ark)
    assert (server.banner_enabled, server.banner_channel, server.banner_type) == (True, 123456789012345678, BannerType.IMAGE)
    assert (server.banner_theme, server.banner_blur, server.banner_steam_art) == ("forest", 5, False)


async def test_upload_background_and_switch_away_removes_file(db_session, tmp_path, monkeypatch):
    import bot.cogs.banner.api as banner_api

    monkeypatch.setattr(banner_api, "BACKGROUND_DIR", tmp_path)
    _, mc, _ = await seed(db_session)
    async with await _client() as client:
        bad = await client.post(f"/banner/servers/{mc}/background", content=b"kein bild", headers={"Content-Type": "image/png"})
        assert bad.status_code == 400
        wrong_type = await client.post(f"/banner/servers/{mc}/background", content=png_bytes(), headers={"Content-Type": "text/plain"})
        assert wrong_type.status_code == 400
        ok = await client.post(f"/banner/servers/{mc}/background", content=png_bytes(), headers={"Content-Type": "image/png"})
        assert ok.status_code == 200
        assert (tmp_path / f"server_{mc}.png").exists()
        assert (await client.get("/banner/config")).json()["servers"][1]["background"] == "image"

        preview = await client.get(f"/banner/servers/{mc}/preview", params={"background": "image", "blur": 2})
        assert preview.status_code == 200 and preview.headers["content-type"] == "image/png"

        await client.put(f"/banner/servers/{mc}", json={"type": "image", "background": "colors", "color_start": "#000000", "color_end": "#ffffff"})
    assert not (tmp_path / f"server_{mc}.png").exists()


async def test_groups_create_members_and_dissolve(db_session):
    ark, mc, fremd = await seed(db_session)
    async with await _client() as client:
        # eigener Banner von ARK wird beim Aufnehmen in die Gruppe abgeschaltet
        await client.put(f"/banner/servers/{ark}", json={"enabled": True, "channel_id": "5", "background": "steam"})
        created = await client.post("/banner/groups", json={"name": "Survival", "channel_id": "7", "member_ids": [ark, mc]})
        assert created.status_code == 200
        group_id = created.json()["id"]
        assert (await client.post("/banner/groups", json={"name": "Survival", "channel_id": "7"})).status_code == 400
        assert (await client.post("/banner/groups", json={"name": "X", "channel_id": "7", "member_ids": [fremd]})).status_code == 400

        data = (await client.get("/banner/config")).json()
        assert data["groups"][0]["member_ids"] == [ark, mc]
        assert data["servers"][0]["enabled"] is False and data["servers"][0]["group_id"] == group_id
        # einzeln anschalten geht nicht, solange in der Gruppe
        assert (await client.put(f"/banner/servers/{ark}", json={"enabled": True, "channel_id": "5"})).status_code == 400

        preview = await client.get(f"/banner/groups/{group_id}/preview", params={"members": f"{ark},{mc}", "theme": "ocean"})
        assert preview.status_code == 200

        await client.put(f"/banner/groups/{group_id}", json={"name": "Survival", "channel_id": "7", "member_ids": [mc], "layout": "separate"})
        data = (await client.get("/banner/config")).json()
        assert data["groups"][0]["member_ids"] == [mc] and data["groups"][0]["layout"] == "separate"
        assert data["servers"][0]["group_id"] is None

        assert (await client.delete(f"/banner/groups/{group_id}")).status_code == 200
    db_session.expire_all()
    assert await db_session.get(BannerGroup, group_id) is None
    assert (await db_session.get(Server, mc)).banner_group_id is None


async def test_preview_for_new_group_without_id(db_session):
    ark, mc, _ = await seed(db_session)
    async with await _client() as client:
        response = await client.get("/banner/groups/0/preview", params={"members": str(ark)})
    assert response.status_code == 200
