from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class ApprovalRequest(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    org_id: int = Field(index=True)
    request_type: str = Field(index=True)
    request_payload: str = Field(default="{}")
    status: str = Field(default="pending", index=True)

    requested_by_user_id: int = Field(foreign_key="user.id", index=True)
    reviewed_by_user_id: Optional[int] = Field(default=None, foreign_key="user.id", index=True)

    requester_note: Optional[str] = None
    review_note: Optional[str] = None
    execution_result: Optional[str] = None

    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    reviewed_at: Optional[datetime] = None
    updated_at: datetime = Field(
        default_factory=datetime.utcnow,
        sa_column_kwargs={"onupdate": datetime.utcnow},
    )
