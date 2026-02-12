from typing import Optional, List
from sqlmodel import Field, SQLModel, Relationship
from datetime import datetime
from enum import Enum

class SubscriptionStatus(str, Enum):
    INCOMPLETE = "incomplete"
    INCOMPLETE_EXPIRED = "incomplete_expired"
    TRIALING = "trialing"
    ACTIVE = "active"
    PAST_DUE = "past_due"
    CANCELED = "canceled"
    UNPAID = "unpaid"
    PAUSED = "paused"

class Subscription(SQLModel, table=True):
    org_id: int = Field(foreign_key="organization.id", primary_key=True)
    stripe_customer_id: Optional[str] = Field(default=None, index=True)
    stripe_subscription_id: Optional[str] = Field(default=None, index=True)
    stripe_price_id: Optional[str] = Field(default=None)
    status: SubscriptionStatus = Field(default=SubscriptionStatus.INCOMPLETE)
    plan_code: str = Field(default="free", index=True)
    link_limit: int = Field(default=2)
    current_period_start: Optional[datetime] = None
    current_period_end: Optional[datetime] = None
    cancel_at_period_end: bool = Field(default=False)
    canceled_at: Optional[datetime] = None
    trial_start: Optional[datetime] = None
    trial_end: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    
    organization: Optional["Organization"] = Relationship(back_populates="subscription")

class PaymentMethod(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    org_id: int = Field(foreign_key="organization.id", index=True)
    stripe_payment_method_id: str = Field(index=True)
    type: str = Field(default="card")
    brand: Optional[str] = None
    last4: Optional[str] = None
    exp_month: Optional[int] = None
    exp_year: Optional[int] = None
    is_default: bool = Field(default=False)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    
class Invoice(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    org_id: int = Field(foreign_key="organization.id", index=True)
    stripe_invoice_id: str = Field(unique=True, index=True)
    stripe_subscription_id: Optional[str] = Field(index=True)
    status: str = Field(index=True)
    total: int
    currency: str = Field(default="usd")
    period_start: Optional[datetime] = None
    period_end: Optional[datetime] = None
    paid_at: Optional[datetime] = None
    pdf_url: Optional[str] = None
    hosted_invoice_url: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

class UsageRecord(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    org_id: int = Field(foreign_key="organization.id", index=True)
    metric_name: str = Field(index=True)
    quantity: int = Field(default=1)
    period_start: datetime = Field(index=True)
    period_end: datetime = Field(index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    
    organization: Optional["Organization"] = Relationship(back_populates="usage_records")

class SubscriptionRead(SQLModel):
    plan_code: str
    status: SubscriptionStatus
    current_period_end: Optional[datetime]
    cancel_at_period_end: bool
    trial_end: Optional[datetime]

class PlanFeature(SQLModel):
    code: str
    name: str
    description: str
    included: bool

class Plan(SQLModel):
    code: str
    name: str
    description: str
    price_monthly: int
    price_yearly: int
    currency: str
    features: List[PlanFeature]
    limits: dict
    is_popular: bool = False
    is_enterprise: bool = False
