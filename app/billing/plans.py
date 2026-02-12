from typing import Dict, List

from app.models.billing import Plan, PlanFeature

DEFAULT_PLAN_CODE = "free"

# Keep legacy codes accepted to avoid breaking existing subscriptions/webhooks.
PLAN_ALIASES: dict[str, str] = {
    "business": "pro",
}

INTERNAL_PLAN_CODES: tuple[str, ...] = ()
PUBLIC_PLAN_CODES: tuple[str, ...] = ("free", "pro", "agency")

PLAN_CONFIG: Dict[str, dict] = {
    "free": {
        "name": "Free",
        "description": "Essential link tracking for individuals",
        "price_monthly": 0,
        "price_yearly": 0,
        "currency": "usd",
        "limits": {
            "sites": 2,
            "site_scans_per_month": 5,
            "link_limit": 2,
            "team_members": 1,
            "webhook_endpoints": 0,
            "api_access": False,
        },
        "features": [
            PlanFeature(code="sites", name="2 Active Sites", description="Track up to 2 websites", included=True),
            PlanFeature(code="weekly", name="Weekly Indexing", description="Standard connection speed", included=True),
            PlanFeature(code="analytics", name="7-Day Analytics", description="Basic visibility retention", included=True),
            PlanFeature(code="json_ld", name="Basic JSON-LD", description="Standard schema markup", included=True),
            PlanFeature(code="llms", name="llms.txt Generation", description="Standard AI compatibility", included=True),
            PlanFeature(code="support", name="Community Support", description="Access to help center", included=True),
        ],
        "is_popular": False,
    },
    "pro": {
        "name": "Pro",
        "description": "Real-time visibility for serious growth",
        "price_monthly": 2900,  # $29.00
        "price_yearly": 29000,
        "currency": "usd",
        "limits": {
            "sites": 20,
            "site_scans_per_month": 60,
            "link_limit": 20,
            "team_members": 3,
            "webhook_endpoints": 5,
            "api_access": True,
        },
        "features": [
            PlanFeature(code="sites", name="20 Active Sites", description="Track up to 20 websites", included=True),
            PlanFeature(code="daily", name="Daily Real-time Indexing", description="Fastest standard updates", included=True),
            PlanFeature(code="analytics", name="30-Day Analytics", description="Extended history", included=True),
            PlanFeature(code="competitors", name="Competitor Tracking", description="Monitor AI visibility", included=True),
            PlanFeature(code="json_ld", name="Advanced JSON-LD", description="Customizable schema", included=True),
            PlanFeature(code="api", name="API Access", description="Programmatic control", included=True),
            PlanFeature(code="support", name="Priority Email Support", description="24h response time", included=True),
        ],
        "is_popular": True,
    },
    "agency": {
        "name": "Agency",
        "description": "Unlimited scale for power users",
        "price_monthly": 9900,  # $99.00
        "price_yearly": 99000,
        "currency": "usd",
        "limits": {
            "sites": 1000000,
            "site_scans_per_month": 1000,
            "link_limit": 1000000,
            "team_members": 10,
            "webhook_endpoints": 20,
            "api_access": True,
        },
        "features": [
            PlanFeature(code="sites", name="Unlimited Sites", description="No limits on tracking", included=True),
            PlanFeature(code="instant", name="Priority Indexing", description="Instant verification", included=True),
            PlanFeature(code="reports", name="White-label PDF Reports", description="Client-ready exports", included=True),
            PlanFeature(code="seats", name="10 Team Seats", description="Collaborative dashboard", included=True),
            PlanFeature(code="retention", name="Unlimited Data History", description="Lifetime analytics", included=True),
            PlanFeature(code="sso", name="SSO & Security", description="Enterprise-grade auth", included=True),
            PlanFeature(code="support", name="Dedicated Account Manager", description="Direct Slack channel", included=True),
        ],
        "is_popular": False,
        "is_enterprise": True,
    },
}


def normalize_plan_code(plan_code: str | None, fallback: str = DEFAULT_PLAN_CODE) -> str:
    candidate = str(plan_code or "").strip().lower()
    if not candidate:
        return fallback
    candidate = PLAN_ALIASES.get(candidate, candidate)
    if candidate not in PLAN_CONFIG:
        return fallback
    return candidate


def is_valid_plan_code(plan_code: str | None) -> bool:
    candidate = str(plan_code or "").strip().lower()
    if not candidate:
        return False
    return candidate in PLAN_CONFIG or candidate in PLAN_ALIASES


def get_plan(plan_code: str | None) -> Plan:
    normalized_code = normalize_plan_code(plan_code)
    config = PLAN_CONFIG.get(normalized_code, PLAN_CONFIG[DEFAULT_PLAN_CODE])
    return Plan(
        code=normalized_code,
        name=config["name"],
        description=config["description"],
        price_monthly=config["price_monthly"],
        price_yearly=config["price_yearly"],
        currency=config["currency"],
        features=config["features"],
        limits=config["limits"],
        is_popular=config.get("is_popular", False),
        is_enterprise=config.get("is_enterprise", False),
    )


def get_all_plans(public_only: bool = False) -> List[Plan]:
    codes = PUBLIC_PLAN_CODES if public_only else INTERNAL_PLAN_CODES + PUBLIC_PLAN_CODES
    return [get_plan(code) for code in codes]


def get_public_plans() -> List[Plan]:
    return get_all_plans(public_only=True)


def get_plan_limit(plan_code: str, limit_name: str) -> int:
    plan_config = PLAN_CONFIG.get(normalize_plan_code(plan_code), PLAN_CONFIG[DEFAULT_PLAN_CODE])
    return int(plan_config["limits"].get(limit_name, 0))


def can_use_feature(plan_code: str, feature_code: str) -> bool:
    plan_config = PLAN_CONFIG.get(normalize_plan_code(plan_code), PLAN_CONFIG[DEFAULT_PLAN_CODE])
    for feature in plan_config["features"]:
        if feature.code == feature_code:
            return feature.included
    return False
