from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL


class Settings(BaseSettings):
    """Zentrale Konfiguration, aus Env-Variablen / .env geladen."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    discord_token: str = ""
    database_url: str = "sqlite+aiosqlite:///./dev.db"

    # Alternative zu DATABASE_URL (z.B. fuer die AMP-Vorlage): einzelne Felder,
    # daraus wird eine MariaDB-URL gebaut - Sonderzeichen im Passwort werden dabei
    # korrekt kodiert. Greift nur, wenn DB_HOST gesetzt und DATABASE_URL NICHT gesetzt ist.
    db_host: str = ""
    db_port: int = 3306
    db_name: str = "wikingerbot"
    db_user: str = "wikingerbot"
    db_password: str = ""

    # Community-Seite (optional, bot/community/): Datenbank der Seite auf demselben
    # MariaDB-Server mit demselben Benutzer wie oben. Leer = keine Anbindung, die
    # Community-Cogs laden dann nicht - der Bot laeuft allein.
    community_db_name: str = ""
    # Alternativ eine komplette URL (z.B. fuer Tests); hat Vorrang vor community_db_name.
    community_database_url: str = ""
    # Oeffentliche Adresse der Seite, fuer Links (z.B. https://wikinger.ipv64.net)
    community_site_url: str = ""

    discord_client_id: str = ""
    discord_client_secret: str = ""
    discord_redirect_uri: str = "http://localhost:8000/auth/callback"
    # Nur falls der Bot auf mehreren Servern ist bzw. die API ohne Bot laeuft:
    # Discord-Server, an dem sich die Web-Oberflaeche anmeldet.
    discord_guild_id: int = 0

    jwt_secret: str = "change-me"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60

    # WebUI (Phase 3): erlaubte Frontend-Origins fuer CORS, plus Ziel-URL fuer
    # den Redirect nach erfolgreichem OAuth2-Login (siehe api/routers/auth.py).
    cors_origins: list[str] = ["http://localhost:5173"]
    frontend_url: str = "http://localhost:5173"

    # Web-Oberflaeche im Bot-Prozess (api/server.py), z.B. in AMP.
    web_enabled: bool = True
    web_host: str = "0.0.0.0"
    web_port: int = 8765
    # Oeffentliche Adresse, z.B. https://bot.wikinger.ipv64.net - daraus werden
    # Frontend-URL und Discord-Redirect (/api/auth/callback) abgeleitet.
    public_url: str = ""
    # Reverse-Proxys (z.B. Edge-Gateway), deren X-Forwarded-* Header geglaubt werden:
    # IPs/Netze, kommagetrennt. Leer = jedem (Standard von frueher).
    trusted_proxies: str = ""

    amp_url: str = "http://localhost:8080"
    amp_user: str = ""
    amp_password: str = ""
    # Eigene AMP-Rolle beim Start einrichten (bot/core/amp_role.py). Mit Super Admin
    # legt der Bot sie an und gibt Super Admin danach ab - ausser amp_keep_super_admin.
    amp_manage_role: bool = True
    # Name oder ID der AMP-Instanz, in der der Bot selbst laeuft (wird ausgeblendet).
    # Leer = automatisch aus dem Pfad (.../instances/<Name>/...) erkannt.
    amp_own_instance: str = ""
    amp_keep_super_admin: bool = False

    # Beim Start des Bots automatisch "alembic upgrade head" ausfuehren (bot/main.py).
    # Fuer den Betrieb in AMP gedacht, wo niemand Migrationen von Hand anstoesst.
    auto_migrate: bool = True
    log_level: str = "INFO"

    @model_validator(mode="after")
    def _database_url_from_parts(self) -> "Settings":
        if self.db_host and "database_url" not in self.model_fields_set:
            self.database_url = URL.create(
                "mysql+asyncmy",
                username=self.db_user,
                password=self.db_password,
                host=self.db_host,
                port=self.db_port,
                database=self.db_name,
            ).render_as_string(hide_password=False)
        return self

    @field_validator("web_port", mode="before")
    @classmethod
    def _web_port_fallback(cls, value):
        # AMP setzt WEB_PORT ueber einen Platzhalter der Vorlage - kommt der einmal
        # unaufgeloest an, lieber Standardport als Absturz beim Start.
        try:
            return int(value)
        except (TypeError, ValueError):
            return 8765

    @model_validator(mode="after")
    def _community_url_from_parts(self) -> "Settings":
        if not self.community_database_url and self.community_db_name and self.db_host:
            self.community_database_url = URL.create(
                "mysql+asyncmy",
                username=self.db_user,
                password=self.db_password,
                host=self.db_host,
                port=self.db_port,
                database=self.community_db_name,
            ).render_as_string(hide_password=False)
        self.community_site_url = self.community_site_url.rstrip("/")
        return self

    @model_validator(mode="after")
    def _urls_from_public_url(self) -> "Settings":
        if self.public_url:
            self.public_url = self.public_url.rstrip("/")
            if "frontend_url" not in self.model_fields_set:
                self.frontend_url = self.public_url
            if "discord_redirect_uri" not in self.model_fields_set:
                self.discord_redirect_uri = f"{self.public_url}/api/auth/callback"
        return self


settings = Settings()
