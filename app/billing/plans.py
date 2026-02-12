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
            "sites": 2, # Matches "2 Links" request
            "site_scans_per_month": 5,
            "link_limit": 2,
            "team_members": 1,
            "webhook_endpoints": 0,
            "api_access": False,
        },
        "features": [
            PlanFeature(
                code="weekly_indexing",
                name="Weekly Indexing",
                description="Standard weekly update frequency",
                included=True,
            ),
            PlanFeature(
                code="basic_analytics",
                name="Basic Analytics",
                description="7-day data retention",
                included=True,
            ),
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
            "sites": 20, # Matches "20 Links" request
            "site_scans_per_month": 60,
            "link_limit": 20,
            "team_members": 3,
            "webhook_endpoints": 5,
            "api_access": True,
        },
        "features": [
            PlanFeature(
                code="daily_indexing",
                name="Daily Real-time Indexing",
                description="Updates detected within 24h",
                included=True,
            ),
            PlanFeature(
                code="dashboard_access",
                name="Full Dashboard Access",
                description="Unlock advanced visualization charts",
                included=True,
            ),
            PlanFeature(
                code="priority_support",
                name="Priority Support",
                description="Email support within 24h",
                included=True,
            ),
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
            "sites": 1000000, # Matches "Unlimited" request
            "site_scans_per_month": 1000,
            "link_limit": 1000000,
            "team_members": 10,
            "webhook_endpoints": 20,
            "api_access": True,
        },
        "features": [
            PlanFeature(
                code="priority_indexing",
                name="Priority Indexing",
                description="Fastest possible indexing speed",
                included=True,
            ),
            PlanFeature(
                code="pdf_reports",
                name="PDF Reports",
                description="White-label PDF exports",
                included=True,
            ),
            PlanFeature(
                code="dedicated_support",
                name="Dedicated Support",
                description="Direct Slack channel access",
                included=True,
            ),
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
