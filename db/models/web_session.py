from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base


class WebSession(Base):
    """Speichert gehashte Discord-Refresh-Tokens fuer WebUI-Logins."""

    __tablename__ = "web_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger)  # Discord User ID
    refresh_token_hash: Mapped[str] = mapped_column(String(255))
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class RememberToken(Base):
    """"Angemeldet bleiben" in der Web-Oberflaeche: langlebiges Anmelde-Token (Cookie),
    hier nur als SHA-256-Hash. Laeuft die kurze Sitzung ab, stellt es eine neue aus;
    Abmelden loescht es."""

    __tablename__ = "web_remember_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger)  # Discord User ID
    guild_id: Mapped[int] = mapped_column(BigInteger)
    level: Mapped[str] = mapped_column(String(20))  # Stufe beim Login (ohne laufenden Bot)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
