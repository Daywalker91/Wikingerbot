from datetime import datetime

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base


class BotSetting(Base):
    """Key-Value-Konfiguration, global (nicht guild-gebunden) - z.B. Bot-weite Schalter.

    Im Gegensatz zu GuildConfig fuer Einstellungen, die den Bot als Ganzes betreffen
    (z.B. ob beim Start automatisch global gesynct wird), nicht einen einzelnen Server.
    """

    __tablename__ = "bot_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
