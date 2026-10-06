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
    assert "Adresse ist unbekannt" in web_link_message()
    assert web_link_message("http://192.0.2.5:8765") == "Web-Oberfläche: http://192.0.2.5:8765"
    monkeypatch.setattr(settings, "public_url", "http://bot.example.org")
    assert web_link_message("http://192.0.2.5:8765") == "Web-Oberfläche: http://bot.example.org"
    monkeypatch.setattr(settings, "web_enabled", False)
    assert "abgeschaltet" in web_link_message()


def test_web_url_from_amp_endpoints():
    from bot.core.amp_client import web_url_from_endpoints

    assert web_url_from_endpoints([{"DisplayName": "App", "Endpoint": "192.0.2.5:8765", "Uri": "http://192.0.2.5:8765"}]) == "http://192.0.2.5:8765"
    assert web_url_from_endpoints([{"Endpoint": "192.0.2.5:8765", "Uri": ""}]) == "http://192.0.2.5:8765"
    assert web_url_from_endpoints([{"Endpoint": "0.0.0.0:8765", "Uri": "http://0.0.0.0:8765"}]) is None
    assert web_url_from_endpoints([]) is None


def test_login_redirect_derived_from_request_without_public_url(monkeypatch):
    monkeypatch.setattr(settings, "public_url", "")
    monkeypatch.setattr(settings, "discord_redirect_uri", "")
    monkeypatch.setattr(settings, "discord_client_id", "123")
    client = TestClient(server.build_app(), base_url="http://192.0.2.5:8765")

    response = client.get("/api/auth/login?guild_id=1", follow_redirects=False)
    location = response.headers["location"]
    assert "redirect_uri=http%3A%2F%2F192.0.2.5%3A8765%2Fapi%2Fauth%2Fcallback" in location


def test_login_redirect_fixed_when_set(monkeypatch):
    monkeypatch.setattr(settings, "discord_redirect_uri", "https://bot.example.org/api/auth/callback")
    client = TestClient(server.build_app(), base_url="http://192.0.2.5:8765")
    location = client.get("/api/auth/login?guild_id=1", follow_redirects=False).headers["location"]
    assert "redirect_uri=https%3A%2F%2Fbot.example.org%2Fapi%2Fauth%2Fcallback" in location


def test_unresolved_port_placeholder_falls_back():
    assert Settings(_env_file=None, web_port="{{$ApplicationPort1}}").web_port == 8765
    assert Settings(_env_file=None, web_port="9000").web_port == 9000


def test_client_id_from_running_bot(monkeypatch):
    from api.routers.auth import client_id

    class Bot:
        application_id = 1523404561895784448
        guilds = []

    monkeypatch.setattr(settings, "discord_client_id", "")
    monkeypatch.setattr(runtime, "bot", Bot())
    assert client_id() == "1523404561895784448"
    monkeypatch.setattr(settings, "discord_client_id", "99")
    assert client_id() == "99"


def test_login_without_secret_explains_instead_of_redirecting(monkeypatch):
    monkeypatch.setattr(settings, "discord_client_id", "123")
    monkeypatch.setattr(settings, "discord_client_secret", "")
    client = TestClient(server.build_app())
    response = client.get("/api/auth/login?guild_id=1", follow_redirects=False)
    assert response.status_code == 503 and "Client Secret" in response.text


def test_trusted_proxies(monkeypatch):
    monkeypatch.setattr(settings, "trusted_proxies", "")
    assert server.forwarded_allow_ips() == "*"
    monkeypatch.setattr(settings, "trusted_proxies", " 192.0.2.35, 198.51.100.0/24 ,")
    assert server.forwarded_allow_ips() == ["192.0.2.35", "198.51.100.0/24"]


def test_login_callback_hints_instead_of_error_page(monkeypatch):
    """Abbrechen bei Discord / kein Mitglied des Servers: zurueck zum Login mit Hinweis."""
    import httpx

    from api.middleware.auth import create_state_token

    monkeypatch.setattr(settings, "frontend_url", "")
    client = TestClient(server.build_app(), base_url="http://192.0.2.5:8765")
    cancelled = client.get("/api/auth/callback?error=access_denied&state=x", follow_redirects=False)
    assert cancelled.headers["location"] == "/login?error=denied"

    def discord(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/oauth2/token"):
            return httpx.Response(200, json={"access_token": "a", "refresh_token": "r", "expires_in": 60})
        if request.url.path.endswith("/users/@me"):
            return httpx.Response(200, json={"id": "42"})
        return httpx.Response(404, json={"message": "Unknown Guild"})  # nicht auf dem Server

    real_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **k: real_client(transport=httpx.MockTransport(discord)))
    state = create_state_token(1, "nonce-abc")
    foreign = client.get(f"/api/auth/callback?code=c&state={state}", follow_redirects=False)
    assert foreign.headers["location"] == "/login?error=failed"  # in einem anderen Browser begonnen (kein Cookie)
    client.cookies.set("oauth_nonce", "nonce-abc")
    outsider = client.get(f"/api/auth/callback?code=c&state={state}", follow_redirects=False)
    assert outsider.headers["location"] == "/login?error=not_member"
