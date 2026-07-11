from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Zentrale Konfiguration, aus Env-Variablen / .env geladen."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    discord_token: str = ""
    database_url: str = "sqlite+aiosqlite:///./dev.db"

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


settings = Settings()
