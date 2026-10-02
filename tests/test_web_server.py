"""Web-Oberflaeche im Bot-Prozess (api/server.py)."""

from fastapi.testclient import TestClient

from api import server
from bot.core import runtime
from bot.core.config import Settings, settings


def make_dist(tmp_path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<html>SPA</html>", encoding="utf-8")
    (tmp_path / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    return tmp_path


def test_api_under_api_prefix_and_spa_everywhere_else(tmp_path):
    client = TestClient(server.build_app(make_dist(tmp_path)))

    assert client.get("/api/health").json() == {"status": "ok"}
    assert client.get("/assets/app.js").text == "console.log(1)"
    # Seiten-Routen gibt es auch als API-Praefix - hier muss die SPA kommen
    for path in ("/", "/servers", "/moderation", "/dashboard"):
        response = client.get(path)
        assert response.status_code == 200 and "SPA" in response.text, path


def test_without_dist_only_api(tmp_path):
    client = TestClient(server.build_app(tmp_path))
    assert client.get("/api/health").status_code == 200
    assert client.get("/dashboard").status_code == 404


def test_guilds_from_running_bot(monkeypatch):
    class Guild:
        def __init__(self, id, name):
            self.id, self.name = id, name

    class Bot:
        guilds = [Guild(1234567890123456789, "Wikinger")]

    monkeypatch.setattr(runtime, "bot", Bot())
    client = TestClient(server.build_app())
    assert client.get("/api/auth/guilds").json() == [{"id": "1234567890123456789", "name": "Wikinger"}]


def test_guilds_fallback_setting(monkeypatch):
    monkeypatch.setattr(runtime, "bot", None)
    monkeypatch.setattr(settings, "discord_guild_id", 42)
    client = TestClient(server.build_app())
    assert client.get("/api/auth/guilds").json() == [{"id": "42", "name": "Discord-Server"}]


def test_jwt_secret_created_once_and_reused(tmp_path, monkeypatch):
    path = tmp_path / "jwt_secret"
    monkeypatch.setattr(settings, "jwt_secret", "change-me")
    server.ensure_jwt_secret(path)
    first = settings.jwt_secret
    assert first != "change-me" and path.read_text(encoding="utf-8") == first

    monkeypatch.setattr(settings, "jwt_secret", "change-me")
    server.ensure_jwt_secret(path)
    assert settings.jwt_secret == first


def test_own_jwt_secret_is_kept(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "jwt_secret", "mein-geheimnis")
    server.ensure_jwt_secret(tmp_path / "jwt_secret")
    assert settings.jwt_secret == "mein-geheimnis"
    assert not (tmp_path / "jwt_secret").exists()


def test_public_url_derives_redirect_and_frontend():
    s = Settings(_env_file=None, public_url="https://bot.example.org/")
    assert s.public_url == "https://bot.example.org"
    assert s.frontend_url == "https://bot.example.org"
    assert s.discord_redirect_uri == "https://bot.example.org/api/auth/callback"


def test_explicit_redirect_wins():
    s = Settings(_env_file=None, public_url="https://bot.example.org", discord_redirect_uri="https://x/cb")
    assert s.discord_redirect_uri == "https://x/cb"


def test_web_link_message(monkeypatch):
    from bot.cogs.admin.cog import web_link_message

    monkeypatch.setattr(settings, "web_enabled", True)
    monkeypatch.setattr(settings, "public_url", "")
    assert "noch keine Web-Adresse" in web_link_message()
    monkeypatch.setattr(settings, "public_url", "http://192.168.4.5:8765")
    assert web_link_message() == "Web-Oberfläche: http://192.168.4.5:8765"
    monkeypatch.setattr(settings, "web_enabled", False)
    assert "abgeschaltet" in web_link_message()


def test_unresolved_port_placeholder_falls_back():
    assert Settings(_env_file=None, web_port="{{$ApplicationPort1}}").web_port == 8765
    assert Settings(_env_file=None, web_port="9000").web_port == 9000
