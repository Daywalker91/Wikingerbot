from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base


class AmpAccount(Base):
    """AMP-Konten, die der Bot fuer Mitglieder der Community-Seite angelegt hat.
    Nur diese fasst er an (sperren, Rolle, Passwort) - nie fremde Konten."""

    __tablename__ = "amp_accounts"

    site_user_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    amp_user_id: Mapped[str] = mapped_column(String(64))
    amp_username: Mapped[str] = mapped_column(String(64))
    disabled: Mapped[bool] = mapped_column(Boolean, default=False)
    # AMP-Rollen-IDs, die der Bot vergeben hat (JSON-Liste)
    role_ids: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
