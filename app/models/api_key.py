from typing import Optional
from sqlmodel import Field, SQLModel, Relationship
from datetime import datetime
import secrets
import hashlib

class ApiKey(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    org_id: int = Field(foreign_key="organization.id", index=True)
    name: str = Field(default="API Key")
    
    key_prefix: str = Field(index=True)
    key_hash: str = Field(unique=True, index=True)
    
    scopes: str = Field(default="read:write")
    rate_limit: Optional[int] = None
    
    last_used_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    created_by: Optional[int] = Field(default=None, foreign_key="user.id")
    
    organization: Optional["Organization"] = Relationship(back_populates="api_keys")

class ApiKeyCreate(SQLModel):
    name: str
    scopes: str = "read:write"
    expires_days: Optional[int] = None

class ApiKeyRead(SQLModel):
    id: int
    name: str
    key_prefix: str
    scopes: str
    last_used_at: Optional[datetime]
    expires_at: Optional[datetime]
    is_active: bool
    created_at: datetime

class ApiKeyWithSecret(SQLModel):
    id: int
    name: str
    key: str
    key_prefix: str
    scopes: str
    expires_at: Optional[datetime]
    created_at: datetime

def generate_api_key() -> tuple[str, str]:
    raw_key = "gl_" + secrets.token_urlsafe(32)
    prefix = raw_key[:11]
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    return raw_key, prefix, key_hash
