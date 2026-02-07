from typing import Optional, List
from datetime import datetime, timedelta
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select, and_, func
from app.models.billing import Subscription, SubscriptionStatus, UsageRecord, Invoice
from app.models.organization import Membership
from app.billing.plans import get_plan_limit, get_plan, can_use_feature
from app.services.stripe_service import stripe_service
import logging

logger = logging.getLogger(__name__)

class SubscriptionService:
    async def get_or_create_subscription(
        self, 
        session: AsyncSession, 
        org_id: int
    ) -> Subscription:
        result = await session.exec(
            select(Subscription).where(Subscription.org_id == org_id)
        )
        subscription = result.first()
        
        if not subscription:
            subscription = Subscription(
                org_id=org_id,
                plan_code="free",
                status=SubscriptionStatus.ACTIVE
            )
            session.add(subscription)
            await session.commit()
            await session.refresh(subscription)
            
        return subscription
    
    async def update_subscription_from_stripe(
        self,
        session: AsyncSession,
        org_id: int,
        stripe_subscription: dict
    ) -> Subscription:
        subscription = await self.get_or_create_subscription(session, org_id)
        
        subscription.stripe_subscription_id = stripe_subscription.get("id")
        subscription.stripe_customer_id = stripe_subscription.get("customer")
        subscription.status = stripe_subscription.get("status", "incomplete")
        subscription.current_period_start = datetime.fromtimestamp(
            stripe_subscription.get("current_period_start", 0)
        ) if stripe_subscription.get("current_period_start") else None
        subscription.current_period_end = datetime.fromtimestamp(
            stripe_subscription.get("current_period_end", 0)
        ) if stripe_subscription.get("current_period_end") else None
        subscription.cancel_at_period_end = stripe_subscription.get("cancel_at_period_end", False)
        subscription.canceled_at = datetime.fromtimestamp(
            stripe_subscription.get("canceled_at", 0)
        ) if stripe_subscription.get("canceled_at") else None
        subscription.trial_start = datetime.fromtimestamp(
            stripe_subscription.get("trial_start", 0)
        ) if stripe_subscription.get("trial_start") else None
        subscription.trial_end = datetime.fromtimestamp(
            stripe_subscription.get("trial_end", 0)
        ) if stripe_subscription.get("trial_end") else None

        items = stripe_subscription.get("items", {}).get("data", [])
        detected_plan_code = None
        if items:
            subscription.stripe_price_id = items[0].get("price", {}).get("id")
            detected_plan_code = stripe_service.get_plan_code_for_price_id(
                subscription.stripe_price_id
            )

        if not detected_plan_code:
            metadata = stripe_subscription.get("metadata", {}) or {}
            metadata_plan = metadata.get("plan_code")
            if isinstance(metadata_plan, str):
                metadata_plan = metadata_plan.strip().lower()
                if metadata_plan:
                    detected_plan_code = metadata_plan

        if detected_plan_code in {"free", "starter", "pro", "business", "enterprise"}:
            subscription.plan_code = detected_plan_code

        session.add(subscription)
        await session.commit()
        await session.refresh(subscription)
        
        return subscription
    
    async def set_plan(
        self,
        session: AsyncSession,
        org_id: int,
        plan_code: str
    ) -> Subscription:
        subscription = await self.get_or_create_subscription(session, org_id)
        subscription.plan_code = plan_code
        session.add(subscription)
        await session.commit()
        await session.refresh(subscription)
        return subscription
    
    async def check_quota(
        self,
        session: AsyncSession,
        org_id: int,
        metric_name: str,
        amount: int = 1
    ) -> tuple[bool, int, int]:
        subscription = await self.get_or_create_subscription(session, org_id)
        plan_code = subscription.plan_code
        limit = get_plan_limit(plan_code, metric_name)
        
        if limit == -1:
            return True, -1, -1
            
        current_usage = await self.get_usage_count(session, org_id, metric_name)
        allowed = (current_usage + amount) <= limit
        
        return allowed, current_usage, limit
    
    async def get_usage_count(
        self,
        session: AsyncSession,
        org_id: int,
        metric_name: str,
        period_days: int = 30
    ) -> int:
        period_start = datetime.utcnow() - timedelta(days=period_days)
        
        result = await session.exec(
            select(func.sum(UsageRecord.quantity))
            .where(
                and_(
                    UsageRecord.org_id == org_id,
                    UsageRecord.metric_name == metric_name,
                    UsageRecord.created_at >= period_start
                )
            )
        )
        
        count = result.first()
        return int(count) if count else 0
    
    async def record_usage(
        self,
        session: AsyncSession,
        org_id: int,
        metric_name: str,
        quantity: int = 1
    ) -> UsageRecord:
        now = datetime.utcnow()
        period_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        if period_start.month == 12:
            next_month = period_start.replace(year=period_start.year + 1, month=1)
        else:
            next_month = period_start.replace(month=period_start.month + 1)
        period_end = next_month - timedelta(seconds=1)
        
        usage = UsageRecord(
            org_id=org_id,
            metric_name=metric_name,
            quantity=quantity,
            period_start=period_start,
            period_end=period_end,
        )
        session.add(usage)
        await session.commit()
        await session.refresh(usage)
        return usage
    
    async def can_use_feature(
        self,
        session: AsyncSession,
        org_id: int,
        feature_code: str
    ) -> bool:
        subscription = await self.get_or_create_subscription(session, org_id)
        return can_use_feature(subscription.plan_code, feature_code)
    
    async def get_subscription_with_org(
        self,
        session: AsyncSession,
        org_id: int
    ) -> Optional[dict]:
        subscription = await self.get_or_create_subscription(session, org_id)
        plan = get_plan(subscription.plan_code)
        from app.models.site import Site
        
        # Count active sites
        sites_count = await session.exec(
            select(func.count(Site.id)).where(Site.org_id == org_id)
        )
        active_sites = sites_count.one()
        
        # Get current month usage
        from datetime import datetime
        current_month_start = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        
        scans_result = await session.exec(
            select(func.sum(UsageRecord.quantity)).where(
                UsageRecord.org_id == org_id,
                UsageRecord.metric_name == "site_scans_per_month",
                UsageRecord.created_at >= current_month_start
            )
        )
        scans_used = scans_result.one() or 0
        
        api_result = await session.exec(
            select(func.sum(UsageRecord.quantity)).where(
                UsageRecord.org_id == org_id,
                UsageRecord.metric_name == "api_calls_per_month",
                UsageRecord.created_at >= current_month_start
            )
        )
        api_used = api_result.one() or 0

        team_result = await session.exec(
            select(func.count(Membership.user_id)).where(Membership.org_id == org_id)
        )
        team_used = team_result.one() or 0
        
        # Build limits with usage
        limits_with_usage = {
            "sites": {
                "used": active_sites,
                "total": plan.limits.get("sites", float('inf'))
            },
            "scans": {
                "used": int(scans_used),
                "total": plan.limits.get("site_scans_per_month", float('inf'))
            },
            "api": {
                "used": int(api_used),
                "total": plan.limits.get("api_calls_per_month", float('inf'))
            },
            "team": {
                "used": int(team_used),
                "total": plan.limits.get("team_members", 1)
            }
        }
        
        return {
            "subscription": subscription,
            "plan": plan,
            "limits": limits_with_usage,
            "features": plan.features
        }
    
    async def sync_subscription_from_stripe(
        self,
        session: AsyncSession,
        stripe_subscription_id: str
    ) -> Optional[Subscription]:
        try:
            stripe_sub = stripe_service.get_subscription(stripe_subscription_id)
            if not stripe_sub:
                return None
                
            result = await session.exec(
                select(Subscription).where(
                    Subscription.stripe_subscription_id == stripe_subscription_id
                )
            )
            subscription = result.first()
            
            if subscription:
                return await self.update_subscription_from_stripe(
                    session, subscription.org_id, stripe_sub
                )
        except Exception as e:
            logger.error(f"Error syncing subscription: {e}")
            
        return None
    
    async def get_upcoming_invoice(
        self,
        session: AsyncSession,
        org_id: int
    ) -> Optional[dict]:
        subscription = await self.get_or_create_subscription(session, org_id)
        
        if not subscription.stripe_customer_id:
            return None
            
        try:
            invoice = stripe_service.get_upcoming_invoice(
                subscription.stripe_customer_id
            )
            if invoice:
                return {
                    "amount_due": invoice.amount_due,
                    "currency": invoice.currency,
                    "period_start": datetime.fromtimestamp(invoice.period_start),
                    "period_end": datetime.fromtimestamp(invoice.period_end),
                    "lines": [
                        {
                            "description": line.description,
                            "amount": line.amount,
                            "period": {
                                "start": datetime.fromtimestamp(line.period.start),
                                "end": datetime.fromtimestamp(line.period.end)
                            }
                        }
                        for line in invoice.lines.data
                    ]
                }
        except Exception as e:
            logger.error(f"Error getting upcoming invoice: {e}")
            
        return None

subscription_service = SubscriptionService()
