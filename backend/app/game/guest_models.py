"""Private guest persistence. Credentials themselves must never enter the DB."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint
from sqlmodel import Field, SQLModel

from app.game.models import timestamp_column


class GuestSession(SQLModel, table=True):
    token_digest: str = Field(primary_key=True, max_length=64)
    owner_id: UUID = Field(
        foreign_key="user.id", nullable=False, unique=True, ondelete="CASCADE"
    )
    public_id: UUID = Field(default_factory=uuid4, unique=True, nullable=False)
    created_at: datetime = Field(sa_column=timestamp_column())
    expires_at: datetime = Field(sa_column=timestamp_column())
    __table_args__ = (
        CheckConstraint("expires_at > created_at", name="ck_guestsession_expiry"),
        CheckConstraint(
            "token_digest ~ '^[0-9a-f]{64}$'", name="ck_guestsession_digest"
        ),
    )
