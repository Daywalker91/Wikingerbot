from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base


class Server(Base):
    """Eine AMP-Instanz (Spiele-Server), einer Guild zugeordnet."""

    __tablename__ = "servers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("guilds.id"))
    instance_name: Mapped[str] = mapped_column(String(100), unique=True)
    amp_instance_id: Mapped[str] = mapped_column(String(100), unique=True)
    display_name: Mapped[str] = mapped_column(String(100))
    # Reine Anzeige-Adresse (wohin sich Spieler verbinden) - NICHT der AMP-API-Endpoint.
    # Die API wird ueber den globalen AMP_URL-Controller + amp_instance_id erreicht.
    host: Mapped[str] = mapped_column(String(255))
    console_channel: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    chat_channel: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    event_channel: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    hidden: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
