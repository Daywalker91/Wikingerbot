"""DATABASE_URL aus Einzelfeldern (DB_HOST, DB_PASSWORD, ...) - fuer die AMP-Vorlage."""

from sqlalchemy.engine import make_url

from bot.core.config import Settings


def test_url_from_parts_encodes_special_chars(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("DB_HOST", "10.0.0.107")
    monkeypatch.setenv("DB_PASSWORD", "p@ss#w:rd/!")
    url = make_url(Settings(_env_file=None).database_url)
    assert url.drivername == "mysql+asyncmy"
    assert url.host == "10.0.0.107"
    assert url.port == 3306
    assert url.database == "wikingerbot"
    assert url.username == "wikingerbot"
    assert url.password == "p@ss#w:rd/!"


def test_database_url_wins_over_parts(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///./other.db")
    monkeypatch.setenv("DB_HOST", "10.0.0.107")
    assert Settings(_env_file=None).database_url == "sqlite+aiosqlite:///./other.db"


def test_default_without_db_settings(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DB_HOST", raising=False)
    assert Settings(_env_file=None).database_url == "sqlite+aiosqlite:///./dev.db"
