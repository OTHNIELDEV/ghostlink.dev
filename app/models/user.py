from typing import Optional, List
from sqlmodel import Field, SQLModel, Relationship
from datetime import datetime

class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    email: str = Field(unique=True, index=True)
    hashed_password: Optional[str] = None
    full_name: Optional[str] = None
    avatar_url: Optional[str] = None
    is_active: bool = Field(default=True)
    is_superuser: bool = Field(default=False)
    email_verified: bool = Field(default=False)
    
    provider: Optional[str] = None
    provider_id: Optional[str] = None

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    last_login_at: Optional[datetime] = None

    sites: List["Site"] = Relationship(back_populates="owner")
    memberships: List["Membership"] = Relationship(back_populates="user")

class UserCreate(SQLModel):
    email: str
    password: str
    full_name: Optional[str] = None

class UserRead(SQLModel):
    id: int
    email: str
    full_name: Optional[str]
    avatar_url: Optional[str]
    email_verified: bool
    created_at: datetime

class UserUpdate(SQLModel):
    full_name: Optional[str] = None
    avatar_url: Optional[str] = None
    email: Optional[str] = None

class UserLogin(SQLModel):
    email: str
    password: str

class UserWithOrgs(SQLModel):
    user: UserRead
    organizations: List[dict]
    default_org_id: Optional[int]
