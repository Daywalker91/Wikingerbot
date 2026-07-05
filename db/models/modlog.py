import enum
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base


class ModAction(str, enum.Enum):
    KICK = "kick"
    BAN = "ban"
    UNBAN = "unban"
    WARN = "warn"
    MUTE = "mute"
    UNMUTE = "unmute"
    TIMEOUT = "timeout"


class ModLogEntry(Base):
    """Protokoll aller Moderationsaktionen."""

    __tablename__ = "modlog"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("guilds.id"))
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))
    mod_id: Mapped[int] = mapped_column(BigInteger)
    action: Mapped[ModAction] = mapped_column(
        Enum(ModAction, values_callable=lambda cls: [item.value for item in cls])
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration: Mapped[int | None] = mapped_column(Integer, nullable=True)  # Sekunden, NULL = permanent
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Warning(Base):
    """Verwarnungen mit Punktesystem."""

    __tablename__ = "warnings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("guilds.id"))
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))
    mod_id: Mapped[int] = mapped_column(BigInteger)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    points: Mapped[int] = mapped_column(Integer, default=1)
    expired: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
