from datetime import datetime

from sqlalchemy import BigInteger, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base


class User(Base):
    """Ein Discord-Nutzer, global (nicht guild-scoped)."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)  # Discord User ID
    username: Mapped[str | None] = mapped_column(String(100), nullable=True)
    steam_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # Zuletzt verwendeter In-Game-Name, wird bei /whitelist request vorausgefuellt/aktualisiert.
    ign: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
