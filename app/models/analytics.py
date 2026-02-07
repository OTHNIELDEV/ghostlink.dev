from typing import Optional
from sqlmodel import Field, SQLModel
from datetime import datetime

class BotVisit(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    site_id: int = Field(index=True)
    bot_name: str = Field(index=True) # e.g., "GPTBot", "Google-Extended", "Human"
    user_agent: str
    served_asset_type: str = Field(default="script") # script, json-ld
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class BridgeEvent(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    site_id: int = Field(index=True)
    session_id: Optional[str] = Field(default=None, index=True)
    event_type: str = Field(index=True)  # pageview, engaged_15s, hidden, leave
    page_url: Optional[str] = Field(default=None)
    page_title: Optional[str] = Field(default=None)
    referrer: Optional[str] = Field(default=None)
    language: Optional[str] = Field(default=None)
    timezone: Optional[str] = Field(default=None)
    viewport: Optional[str] = Field(default=None)
    user_agent: Optional[str] = Field(default=None)
    timestamp: datetime = Field(default_factory=datetime.utcnow, index=True)
