import stripe
from typing import Optional, Dict, Any
from app.core.config import settings
from app.billing.plan_compat import normalize_plan_code

stripe.api_key = settings.STRIPE_SECRET_KEY

class StripeService:
    def __init__(self):
        self.stripe = stripe
        
    def get_or_create_customer(
        self, 
        org_id: int, 
        email: str, 
        name: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> stripe.Customer:
        existing = self.find_customer_by_org_id(org_id)
        if existing:
            return existing
            
        customer_data = {
            "email": email,
            "name": name,
            "metadata": {
                "org_id": str(org_id),
                **(metadata or {})
            }
        }
        
        if settings.STRIPE_TAX_ENABLED:
            customer_data["tax_exempt"] = "none"
            
        return stripe.Customer.create(**customer_data)
    
    def find_customer_by_org_id(self, org_id: int) -> Optional[stripe.Customer]:
        try:
            customers = stripe.Customer.list(
                limit=1,
                metadata={"org_id": str(org_id)}
            )
            if customers.data:
                return customers.data[0]
        except stripe.error.StripeError:
            pass
        return None
    
    def create_checkout_session(
        self,
        customer_id: str,
        price_id: str,
        success_url: str,
        cancel_url: str,
        mode: str = "subscription",
        trial_period_days: Optional[int] = None,
        tax_id_collection: bool = True,
        checkout_metadata: Optional[Dict[str, str]] = None,
        subscription_metadata: Optional[Dict[str, str]] = None,
    ) -> stripe.checkout.Session:
        session_params = {
            "customer": customer_id,
            "payment_method_types": ["card"],
            "line_items": [{
                "price": price_id,
                "quantity": 1,
            }],
            "mode": mode,
            "success_url": success_url,
            "cancel_url": cancel_url,
            "billing_address_collection": "required",
            "allow_promotion_codes": True,
        }

        if checkout_metadata:
            session_params["metadata"] = checkout_metadata

        subscription_data: Dict[str, Any] = {}
        if trial_period_days and trial_period_days > 0:
            subscription_data["trial_period_days"] = trial_period_days
        if subscription_metadata:
            subscription_data["metadata"] = subscription_metadata
        if subscription_data:
            session_params["subscription_data"] = subscription_data
            
        if tax_id_collection and settings.STRIPE_TAX_ENABLED:
            session_params["tax_id_collection"] = {"enabled": True}
            
        return stripe.checkout.Session.create(**session_params)
    
    def create_billing_portal_session(
        self,
        customer_id: str,
        return_url: str
    ) -> stripe.billing_portal.Session:
        return stripe.billing_portal.Session.create(
            customer=customer_id,
            return_url=return_url,
        )
    
    def get_subscription(self, subscription_id: str) -> Optional[stripe.Subscription]:
        try:
            return stripe.Subscription.retrieve(subscription_id)
        except stripe.error.StripeError:
            return None
    
    def cancel_subscription(
        self, 
        subscription_id: str, 
        at_period_end: bool = True
    ) -> stripe.Subscription:
        if at_period_end:
            return stripe.Subscription.modify(
                subscription_id,
                cancel_at_period_end=True
            )
        else:
            return stripe.Subscription.delete(subscription_id)
    
    def reactivate_subscription(self, subscription_id: str) -> stripe.Subscription:
        return stripe.Subscription.modify(
            subscription_id,
            cancel_at_period_end=False
        )
    
    def update_subscription_price(
        self,
        subscription_id: str,
        new_price_id: str,
        proration_behavior: str = "create_prorations"
    ) -> stripe.Subscription:
        subscription = stripe.Subscription.retrieve(subscription_id)
        
        return stripe.Subscription.modify(
            subscription_id,
            items=[{
                "id": subscription["items"]["data"][0]["id"],
                "price": new_price_id,
            }],
            proration_behavior=proration_behavior,
        )
    
    def get_price_id_for_plan(self, plan_code: str, interval: str = "month") -> Optional[str]:
        if interval not in {"month", "year"}:
            return None

        normalized_plan = normalize_plan_code(plan_code)

        # Backward-compatible fallback order:
        # 1) explicit interval key, 2) legacy single key.
        price_candidates = {
            ("free", "month"): settings.STRIPE_PRICE_FREE,
            ("free", "year"): settings.STRIPE_PRICE_FREE,
            ("starter", "month"): settings.STRIPE_PRICE_STARTER_MONTH or settings.STRIPE_PRICE_STARTER,
            ("starter", "year"): settings.STRIPE_PRICE_STARTER_YEAR or settings.STRIPE_PRICE_STARTER,
            ("pro", "month"): settings.STRIPE_PRICE_PRO_MONTH or settings.STRIPE_PRICE_PRO,
            ("pro", "year"): settings.STRIPE_PRICE_PRO_YEAR or settings.STRIPE_PRICE_PRO,
            ("agency", "month"): settings.STRIPE_PRICE_AGENCY_MONTH or settings.STRIPE_PRICE_BUSINESS_MONTH,
            ("agency", "year"): settings.STRIPE_PRICE_AGENCY_YEAR or settings.STRIPE_PRICE_BUSINESS_YEAR,
            ("business", "month"): settings.STRIPE_PRICE_BUSINESS_MONTH or settings.STRIPE_PRICE_BUSINESS,
            ("business", "year"): settings.STRIPE_PRICE_BUSINESS_YEAR or settings.STRIPE_PRICE_BUSINESS,
            ("enterprise", "month"): settings.STRIPE_PRICE_ENTERPRISE_MONTH or settings.STRIPE_PRICE_ENTERPRISE,
            ("enterprise", "year"): settings.STRIPE_PRICE_ENTERPRISE_YEAR or settings.STRIPE_PRICE_ENTERPRISE,
        }
        # Plan aliases are normalized before lookup.
        return price_candidates.get((normalized_plan, interval))

    def get_plan_code_for_price_id(self, price_id: Optional[str]) -> Optional[str]:
        if not price_id:
            return None

        mapping: Dict[str, str] = {}
        price_candidates = {
            "free": [settings.STRIPE_PRICE_FREE],
            "starter": [
                settings.STRIPE_PRICE_STARTER_MONTH,
                settings.STRIPE_PRICE_STARTER_YEAR,
                settings.STRIPE_PRICE_STARTER,
            ],
            "pro": [
                settings.STRIPE_PRICE_PRO_MONTH,
                settings.STRIPE_PRICE_PRO_YEAR,
                settings.STRIPE_PRICE_PRO,
            ],
            "agency": [
                settings.STRIPE_PRICE_AGENCY_MONTH,
                settings.STRIPE_PRICE_AGENCY_YEAR,
                settings.STRIPE_PRICE_BUSINESS_MONTH, # Fallback
                settings.STRIPE_PRICE_BUSINESS_YEAR,  # Fallback
            ],
            "business": [ # Legacy support
                settings.STRIPE_PRICE_BUSINESS_MONTH,
                settings.STRIPE_PRICE_BUSINESS_YEAR,
                settings.STRIPE_PRICE_BUSINESS,
            ],
            "enterprise": [
                settings.STRIPE_PRICE_ENTERPRISE_MONTH,
                settings.STRIPE_PRICE_ENTERPRISE_YEAR,
                settings.STRIPE_PRICE_ENTERPRISE,
            ],
        }

        for plan_code, ids in price_candidates.items():
            for configured_price_id in ids:
                if configured_price_id:
                    mapping[configured_price_id] = normalize_plan_code(plan_code)
        return mapping.get(price_id)
    
    def get_invoices(
        self, 
        customer_id: str, 
        limit: int = 10
    ) -> stripe.ListObject:
        return stripe.Invoice.list(
            customer=customer_id,
            limit=limit
        )
    
    def get_upcoming_invoice(self, customer_id: str) -> Optional[stripe.Invoice]:
        try:
            return stripe.Invoice.upcoming(customer=customer_id)
        except stripe.error.StripeError:
            return None
    
    def construct_webhook_event(
        self, 
        payload: bytes, 
        sig_header: str
    ) -> stripe.Event:
        return stripe.Webhook.construct_event(
            payload,
            sig_header,
            settings.STRIPE_WEBHOOK_SECRET
        )
    
    def get_payment_methods(self, customer_id: str) -> stripe.ListObject:
        return stripe.PaymentMethod.list(
            customer=customer_id,
            type="card"
        )
    
    def attach_payment_method(
        self, 
        customer_id: str, 
        payment_method_id: str
    ) -> stripe.PaymentMethod:
        return stripe.PaymentMethod.attach(
            payment_method_id,
            customer=customer_id
        )
    
    def set_default_payment_method(
        self, 
        customer_id: str, 
        payment_method_id: str
    ) -> stripe.Customer:
        return stripe.Customer.modify(
            customer_id,
            invoice_settings={
                "default_payment_method": payment_method_id
            }
        )

stripe_service = StripeService()
