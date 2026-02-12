from typing import Dict, List

from app.models.billing import Plan, PlanFeature

DEFAULT_PLAN_CODE = "free"

# Keep legacy codes accepted to avoid breaking existing subscriptions/webhooks.
PLAN_ALIASES: dict[str, str] = {
    "business": "pro",
}

INTERNAL_PLAN_CODES: tuple[str, ...] = ("free",)
PUBLIC_PLAN_CODES: tuple[str, ...] = ("starter", "pro", "enterprise")

PLAN_CONFIG: Dict[str, dict] = {
    "free": {
        "name": "Free",
        "description": "Internal fallback plan for canceled or unconfigured subscriptions",
        "price_monthly": 0,
        "price_yearly": 0,
        "currency": "usd",
        "limits": {
            "sites": 1,
            "site_scans_per_month": 5,
            "api_calls_per_month": 100,
            "team_members": 1,
            "analytics_retention_days": 30,
            "reports_export": False,
            "custom_branding": False,
            "priority_support": False,
            "webhook_endpoints": 0,
            "api_access": False,
        },
        "features": [
            PlanFeature(
                code="proof_center_basic",
                name="Proof Center (Basic)",
                description="Track baseline proof KPIs for one site",
                included=True,
            ),
            PlanFeature(
                code="ai_analysis",
                name="AI Site Analysis",
                description="AI-powered site analysis and optimization suggestions",
                included=True,
            ),
            PlanFeature(
                code="json_ld",
                name="JSON-LD Generation",
                description="Automatic structured data generation",
                included=True,
            ),
            PlanFeature(
                code="llms_txt",
                name="LLMs.txt Generation",
                description="AI-friendly site summary generation",
                included=True,
            ),
        ],
        "is_popular": False,
        "is_enterprise": False,
    },
    "starter": {
        "name": "Starter",
        "description": "Weekly proof operations for teams running multiple sites",
        "price_monthly": 1900,
        "price_yearly": 1599,
        "currency": "usd",
        "limits": {
            "sites": 3,
            "site_scans_per_month": 60,
            "api_calls_per_month": 3000,
            "team_members": 3,
            "analytics_retention_days": 90,
            "reports_export": True,
            "custom_branding": False,
            "priority_support": False,
            "webhook_endpoints": 2,
            "api_access": True,
        },
        "features": [
            PlanFeature(
                code="proof_center_team",
                name="Proof Center (Team)",
                description="Track ACR/Citation/AI Assist across team workflows",
                included=True,
            ),
            PlanFeature(
                code="ai_analysis",
                name="AI Site Analysis",
                description="AI-powered site analysis and optimization suggestions",
                included=True,
            ),
            PlanFeature(
                code="json_ld",
                name="JSON-LD Generation",
                description="Automatic structured data generation",
                included=True,
            ),
            PlanFeature(
                code="llms_txt",
                name="LLMs.txt Generation",
                description="AI-friendly site summary generation",
                included=True,
            ),
            PlanFeature(
                code="export_reports",
                name="Export Reports",
                description="PDF and CSV report exports",
                included=True,
            ),
            PlanFeature(
                code="api_access",
                name="API Access",
                description="Programmatic access to GhostLink API",
                included=True,
            ),
        ],
        "is_popular": False,
        "is_enterprise": False,
    },
    "pro": {
        "name": "Pro",
        "description": "Growth-stage proof engine with advanced optimization loops",
        "price_monthly": 4900,
        "price_yearly": 3999,
        "currency": "usd",
        "limits": {
            "sites": 20,
            "site_scans_per_month": 600,
            "api_calls_per_month": 30000,
            "team_members": 10,
            "analytics_retention_days": 365,
            "reports_export": True,
            "custom_branding": True,
            "priority_support": True,
            "webhook_endpoints": 10,
            "api_access": True,
        },
        "features": [
            PlanFeature(
                code="before_after_timeline",
                name="Before/After Timeline",
                description="Compare baseline vs latest answer outcomes",
                included=True,
            ),
            PlanFeature(
                code="advanced_analytics",
                name="Advanced Analytics",
                description="Detailed analytics with historical data",
                included=True,
            ),
            PlanFeature(
                code="scheduled_scans",
                name="Scheduled Scans",
                description="Automatic daily site rescans",
                included=True,
            ),
            PlanFeature(
                code="api_access",
                name="API Access",
                description="Programmatic access to GhostLink API",
                included=True,
            ),
            PlanFeature(
                code="export_reports",
                name="Export Reports",
                description="PDF and CSV report exports",
                included=True,
            ),
            PlanFeature(
                code="custom_branding",
                name="Custom Branding",
                description="Remove GhostLink branding from reports",
                included=True,
            ),
            PlanFeature(
                code="priority_support",
                name="Priority Support",
                description="Priority support with 24h response",
                included=True,
            ),
            PlanFeature(
                code="webhooks",
                name="Webhooks",
                description="Real-time event notifications",
                included=True,
            ),
        ],
        "is_popular": True,
        "is_enterprise": False,
    },
    "enterprise": {
        "name": "Enterprise",
        "description": "Custom enterprise program for AI visibility governance at scale",
        "price_monthly": 0,
        "price_yearly": 0,
        "currency": "usd",
        "limits": {
            "sites": -1,
            "site_scans_per_month": -1,
            "api_calls_per_month": -1,
            "team_members": -1,
            "analytics_retention_days": -1,
            "reports_export": True,
            "custom_branding": True,
            "priority_support": True,
            "webhook_endpoints": -1,
            "api_access": True,
            "dedicated_support": True,
            "sla_guarantee": True,
            "custom_contract": True,
        },
        "features": [
            PlanFeature(
                code="everything_in_pro",
                name="Everything in Pro",
                description="All Pro plan features included",
                included=True,
            ),
            PlanFeature(
                code="executive_briefing",
                name="Executive Proof Briefing",
                description="Custom reporting package for leadership reviews",
                included=True,
            ),
            PlanFeature(
                code="custom_contract",
                name="Custom Contract",
                description="Flexible billing and contract terms",
                included=True,
            ),
            PlanFeature(
                code="dedicated_manager",
                name="Dedicated Account Manager",
                description="Your personal GhostLink specialist",
                included=True,
            ),
            PlanFeature(
                code="sso",
                name="SSO/SAML",
                description="Single sign-on integration",
                included=True,
            ),
            PlanFeature(
                code="security_review",
                name="Security Review",
                description="Annual security assessment",
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
