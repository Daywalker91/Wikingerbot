from pydantic import model_validator
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

    discord_client_id: str = ""
    discord_client_secret: str = ""
    discord_redirect_uri: str = "http://localhost:8000/auth/callback"

    jwt_secret: str = "change-me"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60

    # WebUI (Phase 3): erlaubte Frontend-Origins fuer CORS, plus Ziel-URL fuer
    # den Redirect nach erfolgreichem OAuth2-Login (siehe api/routers/auth.py).
    cors_origins: list[str] = ["http://localhost:5173"]
    frontend_url: str = "http://localhost:5173"

    amp_url: str = "http://localhost:8080"
    amp_user: str = ""
    amp_password: str = ""

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


settings = Settings()
