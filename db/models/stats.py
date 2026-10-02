from datetime import date

from sqlalchemy import BigInteger, Date, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base


class StatsDaily(Base):
    """Tageswerte eines Servers (stats-Cog)."""

    __tablename__ = "stats_daily"

    guild_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("guilds.id"), primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    joins: Mapped[int] = mapped_column(Integer, default=0)
    leaves: Mapped[int] = mapped_column(Integer, default=0)
    messages: Mapped[int] = mapped_column(Integer, default=0)
    voice_seconds: Mapped[int] = mapped_column(Integer, default=0)


class StatsMemberDaily(Base):
    """Tageswerte pro Mitglied - nur Zaehler, nie Inhalte. Wird nach
    stats_retention_days (Standard 90) geloescht. Bewusst ohne FK auf users,
    damit nicht jede Nachricht erst einen User-Eintrag braucht."""

    __tablename__ = "stats_member_daily"

    guild_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("guilds.id"), primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    messages: Mapped[int] = mapped_column(Integer, default=0)
    voice_seconds: Mapped[int] = mapped_column(Integer, default=0)
