import enum
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base


class WhitelistStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"


class WhitelistRequest(Base):
    """Anfrage eines Nutzers, auf einem Server whitelisted zu werden."""

    __tablename__ = "whitelist_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))
    server_id: Mapped[int] = mapped_column(Integer, ForeignKey("servers.id"))
    ign: Mapped[str] = mapped_column(String(100))  # In-Game Name
    status: Mapped[WhitelistStatus] = mapped_column(
        Enum(WhitelistStatus, values_callable=lambda cls: [item.value for item in cls]),
        default=WhitelistStatus.PENDING,
    )
    handled_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # Nachricht mit den Accept/Deny-Buttons - noetig fuer Neustart-sichere Views und
    # zum Editieren der Nachricht nach der Entscheidung.
    review_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
