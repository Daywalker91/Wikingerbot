"""WebUI im Bot-Prozess: API unter /api, gebautes Frontend (web/dist) unter /.

In AMP laeuft nur ein Prozess (bot/main.py) - der startet diesen Server neben
dem Discord-Client auf dem AMP-Port (WEB_PORT). Lokal zur Entwicklung bleibt
der getrennte Weg (uvicorn api.main:app + npm run dev) unveraendert.

Die API liegt unter /api statt im Root, weil sich API-Praefixe und Seiten-Pfade
sonst ueberschneiden (/servers, /moderation, /whitelist gibt es in beiden).
"""

import asyncio
import contextlib
import logging
import secrets
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.staticfiles import StaticFiles

from api.main import app as api_app
from bot.core.config import settings

log = logging.getLogger("wikingerbot.web")

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "web" / "dist"
JWT_SECRET_FILE = ROOT / "data" / "jwt_secret"


class SPAStaticFiles(StaticFiles):
    """Liefert fuer unbekannte Pfade index.html aus - die Seiten-Routen
    (/dashboard, /servers, ...) loest React Router im Browser auf."""

    async def get_response(self, path, scope):
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as error:
            if error.status_code != 404:
                raise
            return await super().get_response("index.html", scope)


def build_app(dist: Path = DIST) -> FastAPI:
    app = FastAPI(title="WikingerBot", docs_url=None, redoc_url=None, openapi_url=None)
    app.mount("/api", api_app)
    if (dist / "index.html").exists():
        app.mount("/", SPAStaticFiles(directory=dist, html=True), name="web")
    else:
        log.warning("Web-Oberflaeche nicht gefunden (%s) - es laeuft nur die API.", dist)
    return app


def ensure_jwt_secret(path: Path = JWT_SECRET_FILE) -> None:
    """Ohne eigenes JWT_SECRET wuerde mit dem oeffentlich bekannten Standardwert
    signiert - dann einmalig ein zufaelliges erzeugen und in data/ ablegen
    (bleibt bei Updates erhalten, Logins ueberleben also Neustarts)."""
    if settings.jwt_secret != "change-me":
        return
    if path.exists() and path.read_text(encoding="utf-8").strip():
        settings.jwt_secret = path.read_text(encoding="utf-8").strip()
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    settings.jwt_secret = secrets.token_urlsafe(48)
    path.write_text(settings.jwt_secret, encoding="utf-8")
    log.info("Neues JWT-Secret erzeugt (%s).", path)


def use_same_origin_urls() -> None:
    """Seite und API kommen hier vom selben Host. Ohne PUBLIC_URL (und ohne einzeln
    gesetzte Werte) werden die Entwicklungs-Standardwerte (localhost:5173/8000)
    deshalb geleert: Weiterleitungen bleiben relativ, der Discord-Redirect wird
    aus der aufgerufenen Adresse gebildet (api/routers/auth.py)."""
    if settings.public_url:
        return
    if "frontend_url" not in settings.model_fields_set:
        settings.frontend_url = ""
    if "discord_redirect_uri" not in settings.model_fields_set:
        settings.discord_redirect_uri = ""


def forwarded_allow_ips() -> list[str] | str:
    """TRUSTED_PROXIES als Liste fuer uvicorn (IPs oder Netze wie 10.42.0.0/16).
    Leer: jedem glauben - bequem im eigenen Netz, aber dann kann jeder, der den
    Port direkt erreicht, sich per X-Forwarded-Proto als https ausgeben."""
    entries = [e.strip() for e in settings.trusted_proxies.split(",") if e.strip()]
    return entries or "*"


class _Server(uvicorn.Server):
    # Strg+C/SIGTERM behandelt bot/main.py fuer den ganzen Prozess - uvicorn soll
    # sich dort nicht dazwischenhaengen.
    @contextlib.contextmanager
    def capture_signals(self):
        yield


class WebServer:
    def __init__(self) -> None:
        self._server: _Server | None = None
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        ensure_jwt_secret()
        use_same_origin_urls()
        config = uvicorn.Config(
            build_app(),
            host=settings.web_host,
            port=settings.web_port,
            log_config=None,
            access_log=False,
            proxy_headers=True,
            forwarded_allow_ips=forwarded_allow_ips(),
        )
        self._server = _Server(config)
        self._task = asyncio.create_task(self._server.serve())
        if settings.public_url:
            log.info("Web-Oberflaeche auf Port %d (%s)", settings.web_port, settings.public_url)
        else:
            log.info("Web-Oberflaeche auf Port %d (Link: /bot web)", settings.web_port)

    async def stop(self) -> None:
        if self._server is None or self._task is None:
            return
        self._server.should_exit = True
        with contextlib.suppress(Exception):
            await asyncio.wait_for(self._task, timeout=10)
