from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base


class PanelRoleRequest(Base):
    """Anfrage ueber einen Panel-Knopf mit Bestaetigung (bot/cogs/roles/requests.py).

    status: pending | approved | denied | revoked (wieder entzogen) | cancelled (Mitglied weg, Rolle nicht vergebbar)."""

    __tablename__ = "panel_role_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("guilds.id"))
    user_id: Mapped[int] = mapped_column(BigInteger)  # Discord-ID
    role_id: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(10), default="pending")
    decided_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)  # Nachricht im Mod-Log
    message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
