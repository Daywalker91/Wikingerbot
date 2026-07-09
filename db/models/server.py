import enum
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Enum, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base


class ConsoleFilterMode(str, enum.Enum):
    OFF = "off"
    BLACKLIST = "blacklist"
    WHITELIST = "whitelist"


class BannerType(str, enum.Enum):
    EMBED = "embed"
    IMAGE = "image"


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
    # Rauschunterdrueckung fuer die Konsolen-Bridge - Default blacklist, damit
    # die eingebauten Standardmuster ohne Konfiguration greifen.
    console_filter_mode: Mapped[ConsoleFilterMode] = mapped_column(
        Enum(ConsoleFilterMode, values_callable=lambda cls: [item.value for item in cls]),
        default=ConsoleFilterMode.BLACKLIST,
    )
    # Rolle, die bei Whitelist-Freigabe fuer diesen Server automatisch vergeben wird.
    discord_role_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    hidden: Mapped[bool] = mapped_column(Boolean, default=False)
    banner_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    banner_channel: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # Bestehende Banner-Nachricht - wird editiert statt neu gepostet, solange sie existiert.
    banner_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    banner_type: Mapped[BannerType] = mapped_column(
        Enum(BannerType, values_callable=lambda cls: [item.value for item in cls]),
        default=BannerType.EMBED,
    )
    banner_theme: Mapped[str | None] = mapped_column(String(50), nullable=True)
    banner_background_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    banner_color_start: Mapped[str | None] = mapped_column(String(7), nullable=True)
    banner_color_end: Mapped[str | None] = mapped_column(String(7), nullable=True)
    # Nur relevant, wenn ein eigenes Bild/Steam-Artwork aktiv ist (dort wirken
    # banner_color_start/_end nicht, weil das Bild Vorrang vor einem Verlauf hat).
    banner_text_color: Mapped[str | None] = mapped_column(String(7), nullable=True)
    banner_blur: Mapped[int] = mapped_column(Integer, default=0)
    # Aus AMPs DisplayImageSource ("steam:<appid>") automatisch erkannt, manuell
    # per /server steam_appid ueberschreibbar - treibt den Steam-Artwork-Abruf.
    steam_app_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Gehoert dieser Server zu einer Banner-Gruppe, hat die Gruppe Vorrang vor
    # seinem eigenen banner_enabled (siehe banner-Cog).
    banner_group_id: Mapped[int | None] = mapped_column(
        ForeignKey("banner_groups.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
