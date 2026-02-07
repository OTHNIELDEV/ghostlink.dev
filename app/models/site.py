import uuid
from typing import Optional
from sqlmodel import Field, SQLModel, Relationship
from datetime import datetime
from sqlalchemy import Column, Text

class SiteBase(SQLModel):
    url: str = Field(index=True)

class Site(SiteBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    script_id: str = Field(default_factory=lambda: str(uuid.uuid4()), index=True, unique=True)
    status: str = Field(default="pending")
    error_msg: Optional[str] = Field(default=None)
    custom_instruction: Optional[str] = Field(default=None)

    # Core Analysis Engine fields
    title: Optional[str] = Field(default=None)
    meta_description: Optional[str] = Field(default=None)
    json_ld: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    llms_txt: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    
    json_ld_content: Optional[str] = Field(default=None)
    llms_txt_content: Optional[str] = Field(default=None)
    seo_description: Optional[str] = Field(default=None)
    schema_type: Optional[str] = Field(default="WebSite")
    
    ai_analysis_json: Optional[str] = Field(default=None)
    ai_score: int = Field(default=0)
    
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(
        default_factory=datetime.utcnow,
        sa_column_kwargs={"onupdate": datetime.utcnow},
    )
    last_scanned_at: Optional[datetime] = Field(default=None)

    owner_id: Optional[int] = Field(default=None, foreign_key="user.id")
    org_id: Optional[int] = Field(default=None, foreign_key="organization.id", index=True)
    
    owner: Optional["User"] = Relationship(back_populates="sites")
    organization: Optional["Organization"] = Relationship(back_populates="sites")

class SiteCreate(SiteBase):
    org_id: Optional[int] = None

class SiteRead(SiteBase):
    id: int
    script_id: str
    status: str
    ai_score: int
    schema_type: Optional[str]
    seo_description: Optional[str]
    created_at: datetime
    last_scanned_at: Optional[datetime]

class SiteUpdate(SQLModel):
    custom_instruction: Optional[str] = None
    url: Optional[str] = None
