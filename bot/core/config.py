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


settings = Settings()
