from fastapi import APIRouter, Request, HTTPException, Depends
from fastapi.responses import JSONResponse
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select
from app.db.engine import get_session
from app.services.stripe_service import stripe_service
from app.services.subscription_service import subscription_service
from app.models.billing import Subscription, Invoice
from app.models.organization import Organization
from app.models.webhook_event import ProcessedWebhookEvent
from datetime import datetime
from sqlalchemy.exc import IntegrityError
import logging

router = APIRouter(tags=["webhooks"])
logger = logging.getLogger(__name__)

@router.post("/stripe")
async def stripe_webhook(request: Request, session: AsyncSession = Depends(get_session)):
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")
    
    if not sig_header:
        logger.warning("Stripe webhook missing signature")
        raise HTTPException(status_code=400, detail="Missing signature")
    
    try:
        event = stripe_service.construct_webhook_event(payload, sig_header)
    except Exception as e:
        logger.error(f"Stripe webhook error: {e}")
        raise HTTPException(status_code=400, detail=f"Webhook error: {str(e)}")

    webhook_event_result = await session.exec(
        select(ProcessedWebhookEvent).where(
            ProcessedWebhookEvent.provider == "stripe",
            ProcessedWebhookEvent.event_id == event.id
        )
    )
    webhook_event = webhook_event_result.first()

    if webhook_event and webhook_event.status == "processed":
        logger.info(f"Skipping duplicate event: {event.id}")
        return {"received": True, "duplicate": True}

    if webhook_event:
        webhook_event.status = "processing"
        webhook_event.error_msg = None
        webhook_event.event_type = event.type
        webhook_event.updated_at = datetime.utcnow()
        session.add(webhook_event)
        await session.commit()
    else:
        webhook_event = ProcessedWebhookEvent(
            provider="stripe",
            event_id=event.id,
            event_type=event.type,
            status="processing",
        )
        session.add(webhook_event)
        try:
            await session.commit()
            await session.refresh(webhook_event)
        except IntegrityError:
            await session.rollback()
            logger.info(f"Skipping duplicate event (race): {event.id}")
            return {"received": True, "duplicate": True}

    try:
        await handle_stripe_event(session, event)
        webhook_event.status = "processed"
        webhook_event.error_msg = None
        webhook_event.processed_at = datetime.utcnow()
        webhook_event.updated_at = datetime.utcnow()
        session.add(webhook_event)
        await session.commit()
    except Exception as e:
        logger.error(f"Error handling stripe event {event.type}: {e}")
        webhook_event.status = "failed"
        webhook_event.error_msg = str(e)[:500]
        webhook_event.updated_at = datetime.utcnow()
        session.add(webhook_event)
        await session.commit()
        raise HTTPException(status_code=500, detail="Error processing webhook")
    
    return {"received": True}

async def handle_stripe_event(session: AsyncSession, event: dict):
    event_type = event.type
    data = event.data.object
    
    handlers = {
        "checkout.session.completed": handle_checkout_completed,
        "customer.subscription.created": handle_subscription_updated,
        "customer.subscription.updated": handle_subscription_updated,
        "customer.subscription.deleted": handle_subscription_deleted,
        "invoice.payment_succeeded": handle_invoice_payment_succeeded,
        "invoice.payment_failed": handle_invoice_payment_failed,
        "customer.subscription.trial_will_end": handle_trial_will_end,
    }
    
    handler = handlers.get(event_type)
    if handler:
        await handler(session, data)
        logger.info(f"Processed {event_type}")
    else:
        logger.debug(f"Unhandled event type: {event_type}")


async def _resolve_org_id_for_billing_event(session: AsyncSession, data: dict) -> int | None:
    metadata = data.get("metadata", {}) or {}
    metadata_org_id = metadata.get("org_id")
    try:
        if metadata_org_id is not None:
            resolved = int(metadata_org_id)
            if resolved > 0:
                return resolved
    except (TypeError, ValueError):
        pass

    subscription_id = data.get("subscription")
    if subscription_id:
        sub = (
            await session.exec(
                select(Subscription).where(
                    Subscription.stripe_subscription_id == subscription_id
                )
            )
        ).first()
        if sub:
            return sub.org_id

    customer_id = data.get("customer")
    if customer_id:
        sub = (
            await session.exec(
                select(Subscription).where(
                    Subscription.stripe_customer_id == customer_id
                )
            )
        ).first()
        if sub:
            return sub.org_id

    return None

async def handle_checkout_completed(session: AsyncSession, data: dict):
    customer_id = data.get("customer")
    subscription_id = data.get("subscription")
    
    if not customer_id or not subscription_id:
        return
    
    try:
        stripe_subscription = stripe_service.get_subscription(subscription_id)
        if not stripe_subscription:
            return
        
        metadata = data.get("metadata", {})
        org_id = metadata.get("org_id")
        
        if org_id:
            await subscription_service.update_subscription_from_stripe(
                session, int(org_id), stripe_subscription
            )
        else:
            result = await session.exec(
                select(Organization).where(
                    Organization.id == int(stripe_subscription.metadata.get("org_id", 0))
                )
            )
            org = result.first()
            if org:
                await subscription_service.update_subscription_from_stripe(
                    session, org.id, stripe_subscription
                )
    except Exception as e:
        logger.error(f"Error handling checkout completed: {e}")

async def handle_subscription_updated(session: AsyncSession, data: dict):
    subscription_id = data.get("id")
    customer_id = data.get("customer")
    
    try:
        result = await session.exec(
            select(Subscription).where(
                Subscription.stripe_subscription_id == subscription_id
            )
        )
        subscription = result.first()
        
        if subscription:
            await subscription_service.update_subscription_from_stripe(
                session, subscription.org_id, data
            )
        else:
            metadata = data.get("metadata", {})
            org_id = metadata.get("org_id")
            
            if org_id:
                await subscription_service.update_subscription_from_stripe(
                    session, int(org_id), data
                )
    except Exception as e:
        logger.error(f"Error handling subscription update: {e}")

async def handle_subscription_deleted(session: AsyncSession, data: dict):
    subscription_id = data.get("id")
    
    try:
        result = await session.exec(
            select(Subscription).where(
                Subscription.stripe_subscription_id == subscription_id
            )
        )
        subscription = result.first()
        
        if subscription:
            subscription.status = "canceled"
            subscription.plan_code = "free"
            session.add(subscription)
            await session.commit()
            
            logger.info(f"Subscription cancelled for org {subscription.org_id}")
    except Exception as e:
        logger.error(f"Error handling subscription deletion: {e}")

async def handle_invoice_payment_succeeded(session: AsyncSession, data: dict):
    try:
        existing = await session.exec(
            select(Invoice).where(
                Invoice.stripe_invoice_id == data.get("id")
            )
        )
        
        if existing.first():
            return

        org_id = await _resolve_org_id_for_billing_event(session, data)
        if not org_id:
            logger.warning(
                "Skipping invoice record because org_id could not be resolved (invoice_id=%s, subscription=%s, customer=%s)",
                data.get("id"),
                data.get("subscription"),
                data.get("customer"),
            )
            return
        
        invoice = Invoice(
            org_id=org_id,
            stripe_invoice_id=data.get("id"),
            stripe_subscription_id=data.get("subscription"),
            status=data.get("status"),
            total=data.get("total"),
            currency=data.get("currency"),
            period_start=datetime.fromtimestamp(data["period_start"]) if data.get("period_start") else None,
            period_end=datetime.fromtimestamp(data["period_end"]) if data.get("period_end") else None,
            paid_at=datetime.fromtimestamp(data.get("status_transitions", {}).get("paid_at", 0)) if data.get("status_transitions", {}).get("paid_at") else None,
            pdf_url=data.get("invoice_pdf"),
            hosted_invoice_url=data.get("hosted_invoice_url")
        )
        
        session.add(invoice)
        await session.commit()
        
        logger.info(f"Invoice recorded: {invoice.stripe_invoice_id}")
    except Exception as e:
        logger.error(f"Error handling invoice payment: {e}")

async def handle_invoice_payment_failed(session: AsyncSession, data: dict):
    subscription_id = data.get("subscription")
    
    if subscription_id:
        try:
            result = await session.exec(
                select(Subscription).where(
                    Subscription.stripe_subscription_id == subscription_id
                )
            )
            subscription = result.first()
            
            if subscription:
                subscription.status = "past_due"
                session.add(subscription)
                await session.commit()
                
                logger.warning(f"Payment failed for org {subscription.org_id}")
        except Exception as e:
            logger.error(f"Error handling payment failure: {e}")

async def handle_trial_will_end(session: AsyncSession, data: dict):
    subscription_id = data.get("id")
    
    try:
        result = await session.exec(
            select(Subscription).where(
                Subscription.stripe_subscription_id == subscription_id
            )
        )
        subscription = result.first()
        
        if subscription:
            logger.info(f"Trial ending soon for org {subscription.org_id}")
    except Exception as e:
        logger.error(f"Error handling trial ending: {e}")
