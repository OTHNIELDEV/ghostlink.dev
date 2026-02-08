from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class AnswerCaptureQuerySet(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    org_id: int = Field(index=True)
    created_by_user_id: int = Field(foreign_key="user.id", index=True)

    name: str = Field(index=True)
    description: Optional[str] = None
    default_brand_terms_json: str = Field(default="[]")
    is_active: bool = Field(default=True, index=True)

    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(
        default_factory=datetime.utcnow,
        sa_column_kwargs={"onupdate": datetime.utcnow},
    )


class AnswerCaptureQueryItem(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    query_set_id: int = Field(foreign_key="answercapturequeryset.id", index=True)

    prompt_text: str
    expected_brand_terms_json: str = Field(default="[]")
    priority: int = Field(default=100, index=True)
    is_active: bool = Field(default=True, index=True)

    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(
        default_factory=datetime.utcnow,
        sa_column_kwargs={"onupdate": datetime.utcnow},
    )


class AnswerCaptureRun(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    org_id: int = Field(index=True)
    query_set_id: int = Field(foreign_key="answercapturequeryset.id", index=True)
    created_by_user_id: int = Field(foreign_key="user.id", index=True)

    status: str = Field(default="pending", index=True)
    provider: str = Field(default="openai", index=True)
    model: str = Field(default="gpt-4o-mini")

    summary_json: str = Field(default="{}")
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(
        default_factory=datetime.utcnow,
        sa_column_kwargs={"onupdate": datetime.utcnow},
    )


class AnswerCaptureResult(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    run_id: int = Field(foreign_key="answercapturerun.id", index=True)
    query_item_id: int = Field(foreign_key="answercapturequeryitem.id", index=True)

    answer_text: str = Field(default="")
    cited_urls_json: str = Field(default="[]")
    has_brand_mention: bool = Field(default=False, index=True)
    has_site_citation: bool = Field(default=False, index=True)
    quality_score: float = Field(default=0.0)

    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)


class AttributionEvent(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    org_id: int = Field(index=True)
    user_id: Optional[int] = Field(default=None, foreign_key="user.id", index=True)
    site_id: Optional[int] = Field(default=None, foreign_key="site.id", index=True)

    session_key: str = Field(index=True)
    source_type: str = Field(default="unknown", index=True)
    source_bot_name: Optional[str] = Field(default=None, index=True)
    referrer: Optional[str] = None
    utm_source: Optional[str] = Field(default=None, index=True)
    utm_medium: Optional[str] = Field(default=None, index=True)
    utm_campaign: Optional[str] = Field(default=None, index=True)

    event_name: str = Field(index=True)
    event_value: float = Field(default=0.0)
    event_timestamp: datetime = Field(default_factory=datetime.utcnow, index=True)
    metadata_json: str = Field(default="{}")

    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)


class AttributionSnapshot(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    org_id: int = Field(index=True)

    period_start: datetime = Field(index=True)
    period_end: datetime = Field(index=True)
    conversions_total: int = Field(default=0)
    ai_assisted_conversions: int = Field(default=0)
    ai_assist_rate_pct: float = Field(default=0.0)
    metadata_json: str = Field(default="{}")

    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)


class OnboardingProgress(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    org_id: int = Field(index=True)
    step_key: str = Field(index=True)
    status: str = Field(default="completed", index=True)
    completed_by_user_id: Optional[int] = Field(default=None, foreign_key="user.id", index=True)
    completed_at: Optional[datetime] = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(
        default_factory=datetime.utcnow,
        sa_column_kwargs={"onupdate": datetime.utcnow},
    )


class ProofSnapshot(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    org_id: int = Field(index=True)
    created_by_user_id: Optional[int] = Field(default=None, foreign_key="user.id", index=True)

    period_start: datetime = Field(index=True)
    period_end: datetime = Field(index=True)
    total_queries_scored: int = Field(default=0)
    answer_capture_rate_pct: float = Field(default=0.0)
    citation_rate_pct: float = Field(default=0.0)
    average_quality_score: float = Field(default=0.0)
    ai_assist_rate_pct: float = Field(default=0.0)
    conversions_total: int = Field(default=0)
    ai_assisted_conversions: int = Field(default=0)
    confidence_level: str = Field(default="low", index=True)
    metadata_json: str = Field(default="{}")

    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
