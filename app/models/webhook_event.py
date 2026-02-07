from typing import Optional
from datetime import datetime
from sqlmodel import Field, SQLModel
from sqlalchemy import UniqueConstraint


class ProcessedWebhookEvent(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint("provider", "event_id", name="uq_webhook_provider_event"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    provider: str = Field(default="stripe", index=True)
    event_id: str = Field(index=True)
    event_type: Optional[str] = Field(default=None, index=True)
    status: str = Field(default="processing", index=True)
    error_msg: Optional[str] = Field(default=None)
    processed_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(
        default_factory=datetime.utcnow,
        sa_column_kwargs={"onupdate": datetime.utcnow},
    )
