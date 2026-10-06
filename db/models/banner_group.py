import enum
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base
from db.models.server import BannerType


class BannerGroupLayout(str, enum.Enum):
    # Ein gestapeltes Bild/Embed mit gemeinsamem Hintergrund/Theme fuer die ganze Gruppe.
    COMBINED = "combined"
    # Ein eigenes Bild/Embed pro Mitglied (mit dessen eigenem Artwork/Theme), alle als
    # Karten (Embeds) in einer gemeinsamen Nachricht.
    SEPARATE = "separate"


class BannerGroup(Base):
    """Buendelt mehrere Server zu einem gemeinsamen Banner in einem Kanal."""

    __tablename__ = "banner_groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("guilds.id"))
    name: Mapped[str] = mapped_column(String(100))
    channel: Mapped[int] = mapped_column(BigInteger)
    message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    banner_type: Mapped[BannerType] = mapped_column(
        Enum(BannerType, values_callable=lambda cls: [item.value for item in cls]),
        default=BannerType.EMBED,
    )
    layout: Mapped[BannerGroupLayout] = mapped_column(
        Enum(BannerGroupLayout, values_callable=lambda cls: [item.value for item in cls]),
        default=BannerGroupLayout.COMBINED,
    )
    # Nur relevant im COMBINED-Layout - im SEPARATE-Layout behaelt jedes Mitglied
    # seine eigenen banner_theme/background_path/color_*/text_color/blur-Felder.
    banner_theme: Mapped[str | None] = mapped_column(String(50), nullable=True)
    banner_background_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    banner_color_start: Mapped[str | None] = mapped_column(String(7), nullable=True)
    banner_color_end: Mapped[str | None] = mapped_column(String(7), nullable=True)
    banner_text_color: Mapped[str | None] = mapped_column(String(7), nullable=True)
    banner_blur: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
