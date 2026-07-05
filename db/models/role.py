import enum
from datetime import datetime
from typing import Iterable

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, Integer, func
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base


class Level(str, enum.Enum):
    """Rollenhierarchie, aufsteigend gereiht (siehe bot/core/permissions.py)."""

    MEMBER = "member"
    MOD = "mod"
    ADMIN = "admin"
    OWNER = "owner"


_ORDER = {Level.MEMBER: 0, Level.MOD: 1, Level.ADMIN: 2, Level.OWNER: 3}


def level_at_least(level: Level, minimum: Level) -> bool:
    return _ORDER[level] >= _ORDER[minimum]


def highest_level(levels: Iterable[Level], default: Level = Level.MEMBER) -> Level:
    return max(levels, key=lambda lvl: _ORDER[lvl], default=default)


class GuildRole(Base):
    """Ordnet eine Discord-Rolle einer Guild einem Berechtigungslevel zu."""

    __tablename__ = "guild_roles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("guilds.id"))
    discord_role_id: Mapped[int] = mapped_column(BigInteger)
    level: Mapped[Level] = mapped_column(
        Enum(Level, values_callable=lambda cls: [item.value for item in cls])
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
