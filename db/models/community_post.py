from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base


class CommunityPost(Base):
    """Welche Discord-Nachricht gehoert zu welchem Beitrag der Community-Seite
    (News, spaeter Events) - damit der Bot sie bei Aenderungen bearbeiten und
    beim Loeschen entfernen kann."""

    __tablename__ = "community_posts"

    kind: Mapped[str] = mapped_column(String(20), primary_key=True)  # "news", "event"
    item_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)  # ID auf der Seite
    guild_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("guilds.id"), primary_key=True)
    channel_id: Mapped[int] = mapped_column(BigInteger)
    message_id: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
