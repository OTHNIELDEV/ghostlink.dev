from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class OptimizationAction(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    site_id: int = Field(foreign_key="site.id", index=True)
    org_id: int = Field(index=True)

    title: str
    source_recommendation: Optional[str] = None
    proposed_instruction: str
    rationale: Optional[str] = None

    status: str = Field(default="pending", index=True)
    loop_version: str = Field(default="v1", index=True)

    decided_by_user_id: Optional[int] = Field(default=None, foreign_key="user.id")
    applied_by_user_id: Optional[int] = Field(default=None, foreign_key="user.id")
    decided_at: Optional[datetime] = None
    applied_at: Optional[datetime] = None
    error_msg: Optional[str] = None

    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(
        default_factory=datetime.utcnow,
        sa_column_kwargs={"onupdate": datetime.utcnow},
    )
