import enum
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Enum, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base


class ConsolePatternKind(str, enum.Enum):
    FILTER = "filter"  # Rauschunterdrueckung (Blacklist/Whitelist)
    EVENT = "event"  # Join/Leave-Erkennung fuer den Event-Kanal


class ConsolePattern(Base):
    """Eigene, zusaetzliche Regex-Muster pro Server (ergaenzen die eingebauten Muster)."""

    __tablename__ = "console_patterns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    server_id: Mapped[int] = mapped_column(Integer, ForeignKey("servers.id"))
    kind: Mapped[ConsolePatternKind] = mapped_column(
        Enum(ConsolePatternKind, values_callable=lambda cls: [item.value for item in cls])
    )
    pattern: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ConsolePatternOverride(Base):
    """Deaktiviert ein eingebautes Muster (per Key) fuer einen bestimmten Server.

    Abwesenheit einer Zeile fuer einen Key bedeutet: das eingebaute Muster
    ist aktiv (Standardverhalten). Nur zum Deaktivieren genutzt.
    """

    __tablename__ = "console_pattern_overrides"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    server_id: Mapped[int] = mapped_column(Integer, ForeignKey("servers.id"))
    kind: Mapped[ConsolePatternKind] = mapped_column(
        Enum(ConsolePatternKind, values_callable=lambda cls: [item.value for item in cls])
    )
    builtin_key: Mapped[str] = mapped_column(String(50))
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
