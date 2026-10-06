from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base


class ServerNotice(Base):
    """Angekuendigter Neustart / angekuendigte Wartung eines Gameservers (servernews-Cog).

    origin: manual (per /wartung, der Bot fuehrt aus) | amp (aus dem AMP-Zeitplan, AMP fuehrt aus)
    kind:   restart | maintenance | stop | update
    status: pending -> running (Server ist gerade unten) -> done | cancelled
    at: Zeitpunkt in UTC (ohne Zeitzone)."""

    __tablename__ = "server_notices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("guilds.id"))
    server_id: Mapped[int] = mapped_column(Integer, ForeignKey("servers.id", ondelete="CASCADE"))
    origin: Mapped[str] = mapped_column(String(10), default="manual")
    kind: Mapped[str] = mapped_column(String(12), default="restart")
    at: Mapped[datetime] = mapped_column(DateTime)
    duration_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    status: Mapped[str] = mapped_column(String(10), default="pending")
    sent_leads: Mapped[str] = mapped_column(Text, default="[]")  # schon gesendete Vorlaufzeiten (Minuten)
    amp_key: Mapped[str | None] = mapped_column(String(80), nullable=True, unique=True)  # Trigger + Zeitpunkt (nur origin amp)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
