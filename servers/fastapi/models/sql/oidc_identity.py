import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Column, DateTime, ForeignKey, String, UniqueConstraint
from sqlmodel import Field, SQLModel

from utils.datetime_utils import get_current_utc_datetime


class OidcIdentity(SQLModel, table=True):
    """Maps an external OIDC subject to a local Presenton user.

    The composite (issuer, subject) pair is unique so the same subject from two
    different identity providers maps to two distinct local accounts.
    """

    __tablename__ = "oidc_identities"
    __table_args__ = (
        UniqueConstraint("issuer", "subject", name="uq_oidc_identities_issuer_subject"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    issuer: str = Field(sa_column=Column(String(512), nullable=False, index=True))
    subject: str = Field(sa_column=Column(String(255), nullable=False))
    user_id: uuid.UUID = Field(
        sa_column=Column(
            ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True
        )
    )
    username: Optional[str] = Field(
        default=None, sa_column=Column(String(128), nullable=True)
    )
    created_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True),
            nullable=False,
            default=get_current_utc_datetime,
        )
    )
