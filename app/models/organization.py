from typing import Optional, List
from sqlmodel import Field, SQLModel, Relationship
from datetime import datetime

class Organization(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    slug: str = Field(unique=True, index=True)
    description: Optional[str] = None
    avatar_url: Optional[str] = None
    website: Optional[str] = None
    preferred_language: Optional[str] = Field(default="auto", max_length=16)
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    
    billing_email: Optional[str] = None
    
    sites: List["Site"] = Relationship(back_populates="organization")
    memberships: List["Membership"] = Relationship(back_populates="organization")
    subscription: Optional["Subscription"] = Relationship(back_populates="organization")
    usage_records: List["UsageRecord"] = Relationship(back_populates="organization")
    api_keys: List["ApiKey"] = Relationship(back_populates="organization")

class Membership(SQLModel, table=True):
    org_id: int = Field(foreign_key="organization.id", primary_key=True)
    user_id: int = Field(foreign_key="user.id", primary_key=True)
    role: str = Field(default="member")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    
    organization: Optional["Organization"] = Relationship(back_populates="memberships")
    user: Optional["User"] = Relationship(back_populates="memberships")

class OrganizationCreate(SQLModel):
    name: str
    slug: str
    description: Optional[str] = None
    website: Optional[str] = None

class OrganizationRead(SQLModel):
    id: int
    name: str
    slug: str
    description: Optional[str]
    avatar_url: Optional[str]
    website: Optional[str]
    preferred_language: Optional[str]
    is_active: bool
    created_at: datetime
    
class OrganizationUpdate(SQLModel):
    name: Optional[str] = None
    description: Optional[str] = None
    website: Optional[str] = None
    preferred_language: Optional[str] = None
    avatar_url: Optional[str] = None
    billing_email: Optional[str] = None
