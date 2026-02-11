import logging
import json
from datetime import datetime, timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import func, select, and_, or_
from app.db.engine import get_session
from app.models.approval import ApprovalRequest
from app.models.site import Site
from app.models.analytics import BotVisit, BridgeEvent, BridgeEventRaw
from app.models.user import User
from app.models.organization import Organization, Membership
from app.routers.users import get_current_user
from app.routers.sites import normalize_site_url, process_site_background, get_org_id_for_user
from app.services.approval_service import approval_service
from app.services.bandit_service import bandit_service
from app.services.innovation_service import innovation_service
from app.services.language_service import (
    LANGUAGE_OPTIONS,
    language_label,
    normalize_language_preference,
    resolve_effective_language_code,
)
from app.services.onboarding_service import onboarding_service
from app.services.proof_service import proof_service
from app.services.report_service import report_service
from app.services.ui_language_service import (
    UI_LANGUAGE_OPTIONS,
    resolve_ui_language,
)
from app.services.i18n_service import get_i18n_messages
from app.services.subscription_service import subscription_service
from app.services.optimization_service import optimization_service
from app.billing.plans import get_all_plans, normalize_plan_code
from app.models.billing import Invoice, Subscription
from starlette.templating import Jinja2Templates
from typing import Any, Optional

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

def tojson_filter(value, indent=None):
    if indent:
        return json.dumps(value, indent=indent, default=str)
    return json.dumps(value, default=str)

templates.env.filters["tojson"] = tojson_filter

logger = logging.getLogger(__name__)


FOOTER_NAV_ITEMS: list[dict[str, str]] = [
    {"slug": "features", "label": "Features", "group": "Product", "href": "/features"},
    {"slug": "pricing", "label": "Pricing", "group": "Product", "href": "/footer/pricing"},
    {"slug": "integrations", "label": "Integrations", "group": "Product", "href": "/footer/integrations"},
    {"slug": "changelog", "label": "Changelog", "group": "Product", "href": "/footer/changelog"},
    {"slug": "documentation", "label": "Documentation", "group": "Product", "href": "/footer/documentation"},
    {"slug": "blog", "label": "Blog", "group": "Resources", "href": "/footer/blog"},
    {"slug": "community", "label": "Community", "group": "Resources", "href": "/footer/community"},
    {"slug": "help-center", "label": "Help Center", "group": "Resources", "href": "/footer/help-center"},
    {"slug": "api-reference", "label": "API Reference", "group": "Resources", "href": "/footer/api-reference"},
    {"slug": "status", "label": "System Status", "group": "Resources", "href": "/footer/status"},
    {"slug": "about", "label": "About Us", "group": "Company", "href": "/footer/about"},
    {"slug": "careers", "label": "Careers", "group": "Company", "href": "/footer/careers"},
    {"slug": "legal", "label": "Legal", "group": "Company", "href": "/footer/legal"},
    {"slug": "contact", "label": "Contact", "group": "Company", "href": "/footer/contact"},
    {"slug": "privacy", "label": "Privacy Policy", "group": "Legal", "href": "/footer/privacy"},
    {"slug": "terms", "label": "Terms of Service", "group": "Legal", "href": "/footer/terms"},
]


FOOTER_PAGE_DETAILS: dict[str, dict[str, Any]] = {
    "features": {
        "eyebrow": "Product",
        "title": "Feature Deep Dive",
        "subtitle": (
            "GhostLink combines AI visibility analysis, proof metrics, and governed optimization loops "
            "into one execution system."
        ),
        "status": "live",
        "highlights": [
            "Automated JSON-LD and llms.txt generation for AI readability.",
            "Measured Proof Center metrics: ACR, Citation Rate, AI Assist Rate.",
            "Approval and audit workflows for safe production changes.",
            "Daily reports for cross-team and client communication.",
        ],
        "customer_confidence": [
            "Every score card has a measured/predicted label.",
            "Onboarding steps map directly to customer outcomes.",
            "Daily summaries expose trend direction and unresolved risk.",
        ],
        "build_ready": [
            "Route and UI are already live.",
            "Can be expanded with persona-specific feature tours.",
        ],
        "primary_cta": {"label": "Open Feature Page", "href": "/features"},
        "secondary_cta": {"label": "Open Manual", "href": "/manual"},
    },
    "pricing": {
        "eyebrow": "Product",
        "title": "Pricing and Packaging",
        "subtitle": "Plans are aligned to proof cadence, governance depth, and team operating scale.",
        "status": "live",
        "highlights": [
            "Transparent 3-tier plan ladder from Starter to Enterprise.",
            "Usage limits tied to sites, scans, and team seats.",
            "Monthly and yearly billing options with Stripe-backed flows.",
            "Enterprise path includes custom contract and governance support.",
        ],
        "customer_confidence": [
            "Show current plan utilization before upgrade prompts.",
            "Highlight expected proof cadence by plan.",
            "Expose overage risk and recommended next tier in advance.",
        ],
        "build_ready": [
            "Billing pages and checkout APIs are already implemented.",
            "Can add ROI calculator as a low-risk incremental page module.",
        ],
        "primary_cta": {"label": "See Pricing Section", "href": "/#pricing"},
        "secondary_cta": {"label": "Open Billing", "href": "/billing"},
    },
    "integrations": {
        "eyebrow": "Product",
        "title": "Integration Paths",
        "subtitle": "Deploy GhostLink once through shared templates, CMS hooks, or tag managers.",
        "status": "live",
        "highlights": [
            "Single insertion model: common layout, GTM, or static head.",
            "Bridge script URL generated per site and org.",
            "Installation detection via script requests and bridge events.",
            "Compatible with static, SSR, and CMS-driven architectures.",
        ],
        "customer_confidence": [
            "Physical deployment confirmation panel with 7-day signal counts.",
            "Clear fallback flow when no signal is detected.",
            "Copy-ready script tags reduce implementation mistakes.",
        ],
        "build_ready": [
            "Integration guide page and telemetry checks already exist.",
            "Can add framework-specific snippets as a docs-only extension.",
        ],
        "primary_cta": {"label": "Open Integration Guide", "href": "/docs/integration-guide"},
        "secondary_cta": {"label": "Open Dashboard", "href": "/dashboard"},
    },
    "changelog": {
        "eyebrow": "Product",
        "title": "Release and Changelog",
        "subtitle": "A customer-readable change narrative reduces uncertainty and supports trust at upgrade time.",
        "status": "live",
        "highlights": [
            "Versioned release notes grouped by customer impact.",
            "Separate flags for feature, fix, and reliability updates.",
            "Migration notes for API and schema-affecting releases.",
            "Roadmap handoff from planned to shipped states.",
        ],
        "customer_confidence": [
            "Users can verify what changed before adopting new workflows.",
            "Critical fixes are easy to audit during incident reviews.",
            "Teams can map releases to KPI shifts in Proof Center.",
        ],
        "build_ready": [
            "Can be implemented as markdown-backed entries under docs/.",
            "No schema change required for MVP version.",
        ],
        "timeline": [
            {
                "date": "2026-02-10",
                "type": "feature",
                "title": "Execution Board and Footer Detail Routes Released",
                "summary": "All footer menu destinations now open dedicated pages with confidence-oriented content.",
                "evidence": "measured",
            },
            {
                "date": "2026-02-10",
                "type": "improvement",
                "title": "Measured/Predicted Evidence Labels Standardized",
                "summary": "Dashboard, proof, report, and daily summary exports now explicitly label evidence type.",
                "evidence": "measured",
            },
            {
                "date": "2026-02-10",
                "type": "improvement",
                "title": "Optimization Reward Loop v2 Baseline Delta",
                "summary": "Auto-evaluation now compares pre/post proof snapshots and records weighted reward feedback.",
                "evidence": "measured",
            },
        ],
        "primary_cta": {"label": "Open Execution Board", "href": "/manual/execution-board"},
        "secondary_cta": {"label": "Open Documentation", "href": "/footer/documentation"},
    },
    "documentation": {
        "eyebrow": "Product",
        "title": "Documentation Hub",
        "subtitle": "Operational docs, API contracts, and implementation guides are consolidated here.",
        "status": "live",
        "highlights": [
            "Integration guide for physical deployment paths.",
            "RBAC policy matrix and routing contracts.",
            "Stripe event transition references for billing safety.",
            "Customer clarity and proof innovation roadmap docs.",
        ],
        "customer_confidence": [
            "Documents explicitly separate measured vs predicted claims.",
            "Every guide has completion signals to avoid ambiguous setup.",
            "Cross-functional owners can follow one source of truth.",
        ],
        "build_ready": [
            "Core docs already exist in the repository.",
            "Can be expanded with generated API docs index.",
        ],
        "primary_cta": {"label": "Open Manual", "href": "/manual"},
        "secondary_cta": {"label": "Open Integration Guide", "href": "/docs/integration-guide"},
    },
    "blog": {
        "eyebrow": "Resources",
        "title": "Insights and Playbooks",
        "subtitle": "Explain AI visibility strategy with practical experiments and customer stories.",
        "status": "ready_to_build",
        "highlights": [
            "Use-case articles by industry and acquisition model.",
            "Before/after case studies tied to measurable proof metrics.",
            "Implementation retrospectives from onboarding teams.",
            "SEO and AI retrieval experimentation notes.",
        ],
        "customer_confidence": [
            "Public case stories demonstrate repeatable outcomes.",
            "Transparent methodology prevents inflated claims.",
            "Readers can reuse checklists in their own deployments.",
        ],
        "build_ready": [
            "Can start as static markdown pages and evolve later.",
            "No backend dependency for initial release.",
        ],
        "primary_cta": {"label": "Open Daily Reports", "href": "/reports/daily"},
        "secondary_cta": {"label": "Open Proof Center", "href": "/proof"},
    },
    "community": {
        "eyebrow": "Resources",
        "title": "Community Workspace",
        "subtitle": "A guided forum and office-hour pattern shortens activation time for new teams.",
        "status": "ready_to_build",
        "highlights": [
            "Weekly implementation office hours.",
            "Shared query sets and attribution event templates.",
            "Common troubleshooting playbooks by framework.",
            "Customer benchmark discussions with confidence labels.",
        ],
        "customer_confidence": [
            "Teams see peers solving the same integration issues.",
            "Faster answers reduce perceived product risk.",
            "Community examples provide realistic expectation ranges.",
        ],
        "build_ready": [
            "Can launch with a simple external community link first.",
            "Internal member-only board can be added in a later phase.",
        ],
        "primary_cta": {"label": "Open Contact", "href": "/footer/contact"},
        "secondary_cta": {"label": "Open Help Center", "href": "/footer/help-center"},
    },
    "help-center": {
        "eyebrow": "Resources",
        "title": "Help Center",
        "subtitle": "Issue-to-resolution runbooks make support repeatable and reduce churn risk.",
        "status": "ready_to_build",
        "highlights": [
            "Top setup failures and immediate remediation checklists.",
            "Billing and permission troubleshooting by role.",
            "Proof KPI interpretation and confidence-level guidance.",
            "Escalation matrix with owner, SLA, and fallback channel.",
        ],
        "customer_confidence": [
            "Problem states have explicit completion criteria.",
            "Users can self-recover before opening a support ticket.",
            "Support responses stay consistent across teams.",
        ],
        "build_ready": [
            "Can be shipped as a static docs section first.",
            "Ticket routing integration can follow after MVP.",
        ],
        "primary_cta": {"label": "Open Integration Guide", "href": "/docs/integration-guide"},
        "secondary_cta": {"label": "Open Contact", "href": "/footer/contact"},
    },
    "api-reference": {
        "eyebrow": "Resources",
        "title": "API Reference",
        "subtitle": "Programmatic endpoints support automation, custom dashboards, and internal platform integration.",
        "status": "live",
        "highlights": [
            "Coverage for onboarding, proof, optimization, attribution, and billing APIs.",
            "Org-scoped access with RBAC-aware behavior.",
            "Audit-friendly request flow for sensitive actions.",
            "Compatible with external BI and automation pipelines.",
        ],
        "customer_confidence": [
            "Teams can validate key metrics independently via API.",
            "Deterministic payload contracts reduce integration risk.",
            "Audit logs support compliance and governance needs.",
        ],
        "build_ready": [
            "API routes already exist and are production-capable.",
            "Can add OpenAPI examples and SDK snippets incrementally.",
        ],
        "primary_cta": {"label": "Open Manual", "href": "/manual"},
        "secondary_cta": {"label": "Open Proof Center", "href": "/proof"},
    },
    "status": {
        "eyebrow": "Resources",
        "title": "System Status",
        "subtitle": "Service transparency builds confidence during both normal operation and incidents.",
        "status": "live",
        "highlights": [
            "Current health for API, crawler, bridge, and report pipelines.",
            "Incident timeline with mitigation and postmortem links.",
            "Historical uptime by component.",
            "Planned maintenance announcements and expected impact.",
        ],
        "customer_confidence": [
            "Users can separate platform issues from integration mistakes.",
            "Incident communication reduces uncertainty during outages.",
            "Historical reliability supports procurement confidence.",
        ],
        "build_ready": [
            "MVP can start as manually updated status timeline.",
            "Automated checks can be added once alerting hooks are wired.",
        ],
        "timeline": [
            {
                "date": "2026-02-10 09:00 UTC",
                "type": "operational",
                "title": "API Gateway",
                "summary": "Operational with no ongoing incident. Average latency within normal range.",
                "evidence": "measured",
            },
            {
                "date": "2026-02-10 09:00 UTC",
                "type": "operational",
                "title": "Crawler + Bridge Event Pipeline",
                "summary": "Operational. Daily report ingestion and proof metrics updates are processing normally.",
                "evidence": "measured",
            },
            {
                "date": "2026-02-10 09:00 UTC",
                "type": "maintenance",
                "title": "Auto Evaluation Window",
                "summary": "Post-action reward evaluator endpoint is active for scheduled org-level runs.",
                "evidence": "measured",
            },
        ],
        "primary_cta": {"label": "Open Daily Reports", "href": "/reports/daily"},
        "secondary_cta": {"label": "Open Contact", "href": "/footer/contact"},
    },
    "about": {
        "eyebrow": "Company",
        "title": "About GhostLink",
        "subtitle": "GhostLink positions AI visibility as an operational discipline, not a one-time setup task.",
        "status": "live",
        "highlights": [
            "Mission: connect website intent to AI answer channels.",
            "Product strategy: measured proof over vanity metrics.",
            "Governance-first architecture for enterprise safety.",
            "Execution model: inspect, apply, verify, and report.",
        ],
        "customer_confidence": [
            "Clear mission reduces ambiguity in product expectations.",
            "Methodology transparency improves buyer trust.",
            "Outcome framing aligns technical work with revenue goals.",
        ],
        "build_ready": [
            "Current product messaging can be reused immediately.",
            "Can be extended with customer success stories over time.",
        ],
        "primary_cta": {"label": "Open Execution Board", "href": "/manual/execution-board"},
        "secondary_cta": {"label": "Open Contact", "href": "/footer/contact"},
    },
    "careers": {
        "eyebrow": "Company",
        "title": "Careers",
        "subtitle": "Hiring pages can reinforce product credibility by showing the operating principles behind delivery.",
        "status": "ready_to_build",
        "highlights": [
            "Role tracks for platform engineering, growth, and customer success.",
            "Hiring principles tied to product reliability and customer outcomes.",
            "Public scorecards for team goals and release quality.",
            "Transparent process and interview expectations.",
        ],
        "customer_confidence": [
            "Strong hiring signal indicates long-term product commitment.",
            "Role transparency demonstrates operational maturity.",
            "Customers see dedicated ownership for their success.",
        ],
        "build_ready": [
            "Can launch with a lean roles board and application form.",
            "No dependency on product database schema.",
        ],
        "primary_cta": {"label": "Open About", "href": "/footer/about"},
        "secondary_cta": {"label": "Open Contact", "href": "/footer/contact"},
    },
    "legal": {
        "eyebrow": "Company",
        "title": "Legal Overview",
        "subtitle": "Legal clarity is a direct conversion factor for procurement and enterprise onboarding.",
        "status": "live",
        "highlights": [
            "Service terms, privacy commitments, and acceptable use boundaries.",
            "Data processing and retention baseline for customer artifacts.",
            "Security and incident communication obligations.",
            "Role and access governance references for admins.",
        ],
        "customer_confidence": [
            "Buyers can validate compliance posture quickly.",
            "Defined responsibilities reduce contracting friction.",
            "Operational safeguards are explicit, not implied.",
        ],
        "build_ready": [
            "Core legal pages are implemented as dedicated routes.",
            "Can add downloadable policy PDFs without backend changes.",
        ],
        "primary_cta": {"label": "Open Privacy Policy", "href": "/footer/privacy"},
        "secondary_cta": {"label": "Open Terms of Service", "href": "/footer/terms"},
    },
    "contact": {
        "eyebrow": "Company",
        "title": "Contact and Escalation",
        "subtitle": "Every customer should know where to ask, escalate, and verify next actions.",
        "status": "live",
        "highlights": [
            "Sales, support, and technical escalation channels.",
            "Response-time expectations by request type.",
            "Implementation prep checklist before onboarding sessions.",
            "Security and compliance inquiry path for procurement teams.",
        ],
        "customer_confidence": [
            "Clear contact channels reduce adoption anxiety.",
            "Escalation paths protect launch timelines.",
            "Support expectations are transparent before purchase.",
        ],
        "build_ready": [
            "Can connect to CRM and ticketing tools incrementally.",
            "Current mailto-based enterprise flow already exists in billing logic.",
        ],
        "primary_cta": {"label": "Email Sales", "href": "mailto:sales@ghostlink.io"},
        "secondary_cta": {"label": "Open Billing", "href": "/billing"},
    },
    "privacy": {
        "eyebrow": "Legal",
        "title": "Privacy Policy",
        "subtitle": "Define how GhostLink handles telemetry, usage data, and customer-provided information.",
        "status": "live",
        "highlights": [
            "Data collection scope and processing purposes.",
            "Storage, retention windows, and deletion requests.",
            "Access controls, auditing, and encryption baseline.",
            "Third-party processors and lawful disclosure handling.",
        ],
        "customer_confidence": [
            "Privacy boundaries are explicit before integration.",
            "Security controls map to enterprise review checklists.",
            "Customers can verify data lifecycle expectations.",
        ],
        "build_ready": [
            "Can maintain policy text directly in this page template.",
            "Version tagging can be added with changelog integration.",
        ],
        "primary_cta": {"label": "Open Legal Overview", "href": "/footer/legal"},
        "secondary_cta": {"label": "Open Terms of Service", "href": "/footer/terms"},
    },
    "terms": {
        "eyebrow": "Legal",
        "title": "Terms of Service",
        "subtitle": "Set clear responsibilities for service use, payment, and operational boundaries.",
        "status": "live",
        "highlights": [
            "Service scope, account obligations, and acceptable use.",
            "Billing terms, renewal behavior, and cancellation conditions.",
            "Support boundaries and warranty disclaimers.",
            "Liability and dispute handling framework.",
        ],
        "customer_confidence": [
            "Contract terms are discoverable from any page footer.",
            "Billing behavior is transparent before checkout.",
            "Risk boundaries are understandable by both legal and ops teams.",
        ],
        "build_ready": [
            "Policy can be refined without schema or API changes.",
            "Can later include signed-version acknowledgment workflow.",
        ],
        "primary_cta": {"label": "Open Privacy Policy", "href": "/footer/privacy"},
        "secondary_cta": {"label": "Open Contact", "href": "/footer/contact"},
    },
}


def _hydrate_site_language(site: Site, accept_language: str | None = None) -> None:
    preferred = normalize_language_preference(site.preferred_language)
    effective = resolve_effective_language_code(
        preferred_language=preferred,
        site_url=site.url,
        accept_language=accept_language,
    )
    site.preferred_language = preferred
    object.__setattr__(site, "effective_language_code", effective)
    object.__setattr__(site, "effective_language_label", language_label(effective))


def _format_approval_summary(request_type: str, payload: dict[str, Any]) -> str:
    if request_type == "billing_plan_change":
        plan_code = str(payload.get("plan_code", "unknown")).upper()
        interval = str(payload.get("interval", "month")).lower()
        interval_label = "Yearly" if interval == "year" else "Monthly"
        return f"Change plan to {plan_code} ({interval_label})"
    if request_type == "billing_cancel":
        at_period_end = bool(payload.get("at_period_end", True))
        return "Cancel subscription at period end" if at_period_end else "Cancel subscription immediately"
    if request_type == "billing_reactivate":
        return "Reactivate current subscription"
    return request_type.replace("_", " ").title()


def _clamp_score(value: Any) -> int:
    try:
        score = int(float(value))
    except Exception:
        score = 0
    return max(0, min(100, score))


def _normalize_report_analysis(site: Site, raw: dict[str, Any] | None) -> dict[str, Any]:
    parsed = raw if isinstance(raw, dict) else {}
    if not parsed and site.status in {"pending", "failed"}:
        return {}

    score_candidate = (
        parsed.get("ai_visibility_score")
        if isinstance(parsed.get("ai_visibility_score"), (int, float, str))
        else site.ai_score
    )
    score = _clamp_score(score_candidate)

    scores = parsed.get("scores") if isinstance(parsed.get("scores"), dict) else {}
    usability = _clamp_score(scores.get("usability", score + 4))
    seo = _clamp_score(scores.get("seo", score))
    content_quality = _clamp_score(scores.get("content_quality", score - 4))
    # Keep report total score aligned with canonical site.ai_score.
    total = score

    summary_keywords = parsed.get("summary_keywords")
    if not isinstance(summary_keywords, list):
        summary_keywords = []
    if not summary_keywords:
        seed = [site.title or "", site.schema_type or "", site.meta_description or site.seo_description or ""]
        summary_keywords = [part for part in seed if part][:3]

    pros = parsed.get("pros") if isinstance(parsed.get("pros"), list) else []
    cons = parsed.get("cons") if isinstance(parsed.get("cons"), list) else []
    recommendations = parsed.get("recommendations") if isinstance(parsed.get("recommendations"), list) else []
    ghostlink_impact = parsed.get("ghostlink_impact") if isinstance(parsed.get("ghostlink_impact"), list) else []

    if not pros:
        pros = [
            "Structured metadata is available for AI parsing.",
            "Bridge script and JSON-LD pipeline are active.",
        ]
    if not cons:
        cons = ["Detailed semantic tuning opportunities remain."]
    if not recommendations:
        recommendations = [
            "Add entity-rich FAQ sections for high-intent queries.",
            "Strengthen title/meta clarity around service outcomes.",
        ]
    if not ghostlink_impact:
        ghostlink_impact = [
            {
                "title": "AI Readability",
                "description": "Improves machine understanding of page intent and entities.",
                "improvement": "+30%",
                "evidence_type": "predicted",
            },
            {
                "title": "Answer Retrieval",
                "description": "Increases context quality for LLM answer generation.",
                "improvement": "+25%",
                "evidence_type": "predicted",
            },
        ]

    normalized_impact: list[dict[str, Any]] = []
    for impact in ghostlink_impact:
        if not isinstance(impact, dict):
            continue
        evidence_type = str(impact.get("evidence_type", "predicted")).strip().lower()
        if evidence_type not in {"predicted", "measured"}:
            evidence_type = "predicted"
        normalized_impact.append(
            {
                "title": str(impact.get("title", "Impact")),
                "description": str(impact.get("description", "")),
                "improvement": str(impact.get("improvement", "-")),
                "evidence_type": evidence_type,
                "source_label": "Measured" if evidence_type == "measured" else "Predicted",
            }
        )
    if not normalized_impact:
        normalized_impact = [
            {
                "title": "AI Readability",
                "description": "Improves machine understanding of page intent and entities.",
                "improvement": "+30%",
                "evidence_type": "predicted",
                "source_label": "Predicted",
            }
        ]

    return {
        "scores": {
            "usability": usability,
            "seo": seo,
            "content_quality": content_quality,
            "total": total,
        },
        "summary_keywords": summary_keywords,
        "pros": pros,
        "cons": cons,
        "recommendations": recommendations,
        "ghostlink_impact": normalized_impact,
    }


async def _serialize_approvals_for_ui(
    session: AsyncSession, rows: list[ApprovalRequest]
) -> list[dict[str, Any]]:
    user_ids: set[int] = set()
    for row in rows:
        if row.requested_by_user_id is not None:
            user_ids.add(row.requested_by_user_id)
        if row.reviewed_by_user_id is not None:
            user_ids.add(row.reviewed_by_user_id)

    user_labels: dict[int, str] = {}
    if user_ids:
        users = (await session.exec(select(User).where(User.id.in_(list(user_ids))))).all()
        user_labels = {
            row.id: (row.full_name or row.email)
            for row in users
            if row.id is not None
        }

    serialized: list[dict[str, Any]] = []
    for row in rows:
        payload = approval_service.parse_request_payload(row)
        execution_result = approval_service.parse_execution_result(row)
        serialized.append(
            {
                "id": row.id,
                "org_id": row.org_id,
                "request_type": row.request_type,
                "request_payload": payload,
                "summary": _format_approval_summary(row.request_type, payload),
                "status": row.status,
                "requested_by_user_id": row.requested_by_user_id,
                "requested_by_label": user_labels.get(row.requested_by_user_id, f"User #{row.requested_by_user_id}"),
                "reviewed_by_user_id": row.reviewed_by_user_id,
                "reviewed_by_label": (
                    user_labels.get(row.reviewed_by_user_id, f"User #{row.reviewed_by_user_id}")
                    if row.reviewed_by_user_id
                    else None
                ),
                "requester_note": row.requester_note,
                "review_note": row.review_note,
                "execution_result": execution_result,
                "created_at": row.created_at,
                "reviewed_at": row.reviewed_at,
                "updated_at": row.updated_at,
            }
        )

    return serialized


async def _get_pending_approval_count(session: AsyncSession, org_id: int) -> int:
    result = await session.exec(
        select(func.count()).select_from(ApprovalRequest).where(
            and_(
                ApprovalRequest.org_id == org_id,
                ApprovalRequest.status == "pending",
            )
        )
    )
    return int(result.one() or 0)


async def _get_approval_status_counts(session: AsyncSession, org_id: int) -> dict[str, int]:
    counts = {
        "all": 0,
        "pending": 0,
        "approved": 0,
        "rejected": 0,
        "failed": 0,
    }
    result = await session.exec(
        select(ApprovalRequest.status, func.count())
        .where(ApprovalRequest.org_id == org_id)
        .group_by(ApprovalRequest.status)
    )
    for status_value, count_value in result.all():
        status_key = str(status_value or "").strip().lower()
        if status_key in counts:
            counts[status_key] = int(count_value or 0)
    counts["all"] = counts["pending"] + counts["approved"] + counts["rejected"] + counts["failed"]
    return counts


async def _get_pending_approvals(
    session: AsyncSession,
    org_id: int,
    limit: int = 5,
) -> list[dict[str, Any]]:
    rows = (
        await session.exec(
            select(ApprovalRequest)
            .where(
                and_(
                    ApprovalRequest.org_id == org_id,
                    ApprovalRequest.status == "pending",
                )
            )
            .order_by(ApprovalRequest.created_at.desc())
            .limit(limit)
        )
    ).all()
    return await _serialize_approvals_for_ui(session, rows)


def _build_plan_value_ladder(current_plan_code: str) -> list[dict[str, Any]]:
    normalized_current_plan = normalize_plan_code(current_plan_code)
    outcome_copy = {
        "starter": {
            "headline": "Weekly Proof Ops",
            "value": "Track proof KPIs across multiple sites and teams.",
        },
        "pro": {
            "headline": "Growth Proof Engine",
            "value": "Scale answer capture runs and conversion attribution.",
        },
        "enterprise": {
            "headline": "Executive AI Visibility Program",
            "value": "Custom governance, SLA, and enterprise-grade rollout.",
        },
    }
    ladders = []
    for plan in get_all_plans(public_only=True):
        limits = plan.limits if isinstance(plan.limits, dict) else {}
        ladders.append(
            {
                "code": plan.code,
                "name": plan.name,
                "headline": outcome_copy.get(plan.code, {}).get("headline", plan.name),
                "value": outcome_copy.get(plan.code, {}).get("value", plan.description),
                "sites_limit": limits.get("sites", 0),
                "scan_limit": limits.get("site_scans_per_month", 0),
                "team_limit": limits.get("team_members", 1),
                "is_current": plan.code == normalized_current_plan,
                "is_enterprise": plan.is_enterprise,
            }
        )
    return ladders


def _build_ui_language_context(request: Request, user: Optional[User]) -> dict[str, Any]:
    preferred = user.preferred_ui_language if user else "auto"
    resolved = resolve_ui_language(
        preferred_language=preferred,
        accept_language=request.headers.get("accept-language"),
    )
    return {
        "ui_language_options": UI_LANGUAGE_OPTIONS,
        "ui_language_preferred": preferred or "auto",
        "ui_language_resolved": resolved,
        "i18n": get_i18n_messages(resolved),
    }

@router.get("/report/{site_id}")
async def report_page(
    request: Request, 
    site_id: int, 
    org_id: int = None,
    session: AsyncSession = Depends(get_session), 
    user: Optional[User] = Depends(get_current_user)
):
    if not user:
        return RedirectResponse(url="/auth/login", status_code=303)
    
    effective_org_id = await get_org_id_for_user(session, user, org_id)
    
    statement = select(Site).where(
        and_(
            Site.id == site_id,
            Site.org_id == effective_org_id
        )
    )
    result = await session.exec(statement)
    site = result.first()
    
    if not site:
        return RedirectResponse(url="/dashboard", status_code=303)
    _hydrate_site_language(site, request.headers.get("accept-language"))
        
    analysis = {}
    if site.ai_analysis_json:
        try:
            analysis = json.loads(site.ai_analysis_json)
        except:
            pass
    analysis = _normalize_report_analysis(site, analysis)

    proof_overview_30d = await proof_service.compute_overview(
        session=session,
        org_id=effective_org_id,
        period_days=30,
    )
    if int(proof_overview_30d.get("total_queries_scored", 0)) > 0:
        analysis.setdefault("ghostlink_impact", [])
        analysis["ghostlink_impact"].append(
            {
                "title": "Measured Answer Capture",
                "description": (
                    f"Measured over last 30 days: "
                    f"ACR {proof_overview_30d.get('answer_capture_rate_pct', 0.0)}%, "
                    f"Citation {proof_overview_30d.get('citation_rate_pct', 0.0)}%, "
                    f"AI Assist {proof_overview_30d.get('ai_assist_rate_pct', 0.0)}%."
                ),
                "improvement": f"Proof Score {proof_overview_30d.get('proof_score', 0.0)}",
                "evidence_type": "measured",
                "source_label": "Measured",
            }
        )
            
    optimization_actions = await optimization_service.list_actions(
        session=session,
        site_id=site.id,
        org_id=effective_org_id,
        include_closed=True,
    )
    bandit_arms = await bandit_service.list_arms(
        session=session,
        org_id=effective_org_id,
        site_id=site.id,
    )
    action_by_id = {action.id: action for action in optimization_actions if action.id is not None}
    bandit_arms_ui = [
        {
            "arm_id": arm.id,
            "action_id": arm.action_id,
            "title": (
                action_by_id[arm.action_id].title
                if arm.action_id in action_by_id
                else f"Action #{arm.action_id}"
            ),
            "status": (
                action_by_id[arm.action_id].status
                if arm.action_id in action_by_id
                else "unknown"
            ),
            "pulls": arm.pulls,
            "average_reward": arm.average_reward,
            "last_reward": arm.last_reward,
            "last_reward_at": arm.last_reward_at,
            "alpha": arm.alpha,
            "beta": arm.beta,
        }
        for arm in bandit_arms
    ]

    seven_days_ago = datetime.utcnow() - timedelta(days=7)
    script_request_count_7d = int(
        (
            await session.exec(
                select(func.count()).select_from(BotVisit).where(
                    and_(
                        BotVisit.site_id == site.id,
                        BotVisit.timestamp >= seven_days_ago,
                    )
                )
            )
        ).one()
        or 0
    )
    bridge_event_count_7d = int(
        (
            await session.exec(
                select(func.count()).select_from(BridgeEvent).where(
                    and_(
                        BridgeEvent.site_id == site.id,
                        BridgeEvent.timestamp >= seven_days_ago,
                    )
                )
            )
        ).one()
        or 0
    )
    installation_detected = (script_request_count_7d + bridge_event_count_7d) > 0
    bridge_script_url = str(request.base_url).rstrip("/") + f"/api/bridge/{site.script_id}.js"

    return templates.TemplateResponse("pages/report.html", {
        "request": request, 
        "site": site, 
        "analysis": analysis,
        "user": user,
        "org_id": effective_org_id,
        "optimization_actions": optimization_actions,
        "bandit_arms": bandit_arms_ui,
        "language_options": LANGUAGE_OPTIONS,
        "proof_overview_30d": proof_overview_30d,
        "installation_status": {
            "detected": installation_detected,
            "script_request_count_7d": script_request_count_7d,
            "bridge_event_count_7d": bridge_event_count_7d,
        },
        "bridge_script_url": bridge_script_url,
        **_build_ui_language_context(request, user),
    })

@router.get("/")
async def landing(request: Request, user: Optional[User] = Depends(get_current_user)):
    plans = get_all_plans(public_only=True)
    return templates.TemplateResponse(
        "pages/landing.html",
        {
            "request": request,
            "user": user,
            "plans": plans,
            **_build_ui_language_context(request, user),
        },
    )

@router.get("/dashboard")
async def dashboard(
    request: Request,
    background_tasks: BackgroundTasks,
    url: str = None,
    org_id: int = None,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user)
):
    if not user:
        return RedirectResponse(url="/auth/login", status_code=303)

    effective_org_id = await get_org_id_for_user(session, user, org_id)
    
    result = await session.exec(
        select(Organization).where(Organization.id == effective_org_id)
    )
    organization = result.first()
    org_preferred_language = normalize_language_preference(
        organization.preferred_language if organization else "auto"
    )

    if url:
        try:
            normalized_url = normalize_site_url(url)
            statement = select(Site).where(
                and_(
                    Site.url == normalized_url,
                    Site.org_id == effective_org_id
                )
            )
            results = await session.exec(statement)
            existing_site = results.first()

            should_start_processing = False
            if existing_site:
                if existing_site.status != "pending":
                    existing_site.status = "pending"
                    existing_site.error_msg = None
                    existing_site.updated_at = datetime.utcnow()
                    session.add(existing_site)
                    await session.commit()
                    await session.refresh(existing_site)
                    should_start_processing = True
            else:
                existing_site = Site(
                    url=normalized_url,
                    status="pending",
                    updated_at=datetime.utcnow(),
                    preferred_language="auto",
                    org_id=effective_org_id,
                    owner_id=user.id
                )
                session.add(existing_site)
                await session.commit()
                await session.refresh(existing_site)
                should_start_processing = True

            if should_start_processing:
                background_tasks.add_task(process_site_background, existing_site.id)
        except ValueError:
            logger.warning("Invalid URL received on dashboard redirect: %s", url)

    statement = select(Site).where(Site.org_id == effective_org_id).order_by(Site.created_at.desc())
    results = await session.exec(statement)
    sites = results.all()
    request_accept_language = request.headers.get("accept-language")
    for site_row in sites:
        _hydrate_site_language(site_row, request_accept_language)
    
    total_ai_impressions = 0
    total_human_visits = 0
    
    site_ids = [site.id for site in sites]
    
    if site_ids:
        query_bots = select(func.count()).select_from(BotVisit).where(
            and_(
                BotVisit.bot_name != "Human/Browser",
                BotVisit.site_id.in_(site_ids)
            )
        )
        result_bots = await session.exec(query_bots)
        total_ai_impressions = result_bots.one()
        
        query_humans = select(func.count()).select_from(BotVisit).where(
            and_(
                BotVisit.bot_name == "Human/Browser",
                BotVisit.site_id.in_(site_ids)
            )
        )
        result_humans = await session.exec(query_humans)
        total_human_visits = result_humans.one()
    
    now = datetime.utcnow()
    seven_days_ago = now - timedelta(days=7)
    fourteen_days_ago = now - timedelta(days=14)
    thirty_days_ago = now - timedelta(days=30)

    scoreboard = {
        "visibility_score": 0,
        "traffic_visibility_score": 0,
        "ai_crawler_visits_7d": 0,
        "ai_crawler_growth_pct": 0.0,
        "human_visits_7d": 0,
        "human_growth_pct": 0.0,
        "active_bots_30d": 0,
        "top_bots_30d": [],
    }

    def _growth_pct(current: int, previous: int) -> float:
        if previous <= 0:
            return 100.0 if current > 0 else 0.0
        return round(((current - previous) / previous) * 100.0, 1)

    if site_ids:
        query_recent_30 = select(BotVisit).where(
            and_(
                BotVisit.timestamp >= thirty_days_ago,
                BotVisit.site_id.in_(site_ids)
            )
        )
        result_recent_30 = await session.exec(query_recent_30)
        recent_visits_30d = result_recent_30.all()

        bot_counts: dict[str, int] = {}
        ai_crawler_visits_7d = 0
        ai_crawler_visits_prev_7d = 0
        human_visits_7d = 0
        human_visits_prev_7d = 0

        for visit in recent_visits_30d:
            is_human = visit.bot_name == "Human/Browser"

            if not is_human:
                bot_counts[visit.bot_name] = bot_counts.get(visit.bot_name, 0) + 1

            if visit.timestamp >= seven_days_ago:
                if is_human:
                    human_visits_7d += 1
                else:
                    ai_crawler_visits_7d += 1
            elif visit.timestamp >= fourteen_days_ago:
                if is_human:
                    human_visits_prev_7d += 1
                else:
                    ai_crawler_visits_prev_7d += 1

        ai_visits_30d = sum(bot_counts.values())
        active_bots_30d = len(bot_counts)

        top_bots = []
        if ai_visits_30d > 0:
            for bot_name, count in sorted(bot_counts.items(), key=lambda x: x[1], reverse=True)[:5]:
                top_bots.append({
                    "name": bot_name,
                    "count": count,
                    "share_pct": round((count / ai_visits_30d) * 100.0, 1)
                })

        volume_score = min(60, ai_visits_30d * 2)
        diversity_score = min(25, active_bots_30d * 5)
        recency_score = 15 if ai_crawler_visits_7d > 0 else 0
        traffic_visibility_score = min(100, volume_score + diversity_score + recency_score)
        scored_sites = [
            _clamp_score(site_row.ai_score)
            for site_row in sites
            if site_row.status in {"active", "completed"}
        ]
        visibility_score = round(sum(scored_sites) / len(scored_sites)) if scored_sites else 0

        scoreboard = {
            "visibility_score": visibility_score,
            "traffic_visibility_score": traffic_visibility_score,
            "ai_crawler_visits_7d": ai_crawler_visits_7d,
            "ai_crawler_growth_pct": _growth_pct(ai_crawler_visits_7d, ai_crawler_visits_prev_7d),
            "human_visits_7d": human_visits_7d,
            "human_growth_pct": _growth_pct(human_visits_7d, human_visits_prev_7d),
            "active_bots_30d": active_bots_30d,
            "top_bots_30d": top_bots,
        }
    
    chart_data = {}
    for i in range(7):
        d = (datetime.utcnow() - timedelta(days=i)).strftime("%Y-%m-%d")
        chart_data[d] = 0
        
    if site_ids:
        query_recent = select(BotVisit).where(
            and_(
                BotVisit.timestamp >= seven_days_ago,
                BotVisit.site_id.in_(site_ids)
            )
        )
        results_recent = await session.exec(query_recent)
        recent_visits = results_recent.all()
        
        for visit in recent_visits:
            date_str = visit.timestamp.strftime("%Y-%m-%d")
            if visit.bot_name != "Human/Browser" and date_str in chart_data:
                chart_data[date_str] += 1
                
    sorted_dates = sorted(chart_data.keys())
    chart_labels = sorted_dates
    chart_values = [chart_data[d] for d in sorted_dates]
    
    subscription_info = await subscription_service.get_subscription_with_org(
        session, effective_org_id
    )
    
    org_list_result = await session.exec(
        select(Organization, Membership)
        .join(Membership)
        .where(Membership.user_id == user.id)
    )
    organizations = []
    membership_role = "member"
    for org, membership in org_list_result.all():
        organizations.append({
            "id": org.id,
            "name": org.name,
            "slug": org.slug,
            "role": membership.role
        })
        if org.id == effective_org_id:
            membership_role = membership.role

    pending_approval_count = await _get_pending_approval_count(session, effective_org_id)
    pending_approvals = await _get_pending_approvals(session, effective_org_id, limit=5)
    onboarding = await onboarding_service.get_status(
        session=session,
        org_id=effective_org_id,
        user_id=user.id,
    )
    proof_overview_30d = await proof_service.compute_overview(
        session=session,
        org_id=effective_org_id,
        period_days=30,
    )
    
    return templates.TemplateResponse("pages/dashboard.html", {
        "request": request, 
        "sites": sites,
        "total_ai_impressions": total_ai_impressions,
        "total_human_visits": total_human_visits,
        "chart_labels": chart_labels,
        "chart_values": chart_values,
        "active_page": "dashboard",
        "user": user,
        "organization": organization,
        "org_preferred_language": org_preferred_language,
        "organizations": organizations,
        "org_id": effective_org_id,
        "subscription": subscription_info,
        "scoreboard": scoreboard,
        "pending_approval_count": pending_approval_count,
        "pending_approvals": pending_approvals,
        "can_review_approvals": membership_role in {"owner", "admin"},
        "language_options": LANGUAGE_OPTIONS,
        "onboarding": onboarding,
        "proof_overview_30d": proof_overview_30d,
        **_build_ui_language_context(request, user),
    })

@router.get("/settings")
async def settings_page(
    request: Request, 
    org_id: int = None,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user)
):
    if not user: 
        return RedirectResponse(url="/auth/login", status_code=303)
    
    effective_org_id = await get_org_id_for_user(session, user, org_id)
    membership = (
        await session.exec(
            select(Membership).where(
                and_(
                    Membership.org_id == effective_org_id,
                    Membership.user_id == user.id,
                )
            )
        )
    ).first()
    if not membership:
        return RedirectResponse(url="/dashboard", status_code=303)
    pending_approval_count = await _get_pending_approval_count(session, effective_org_id)
    
    return templates.TemplateResponse("pages/settings.html", {
        "request": request, 
        "active_page": "settings", 
        "user": user,
        "org_id": effective_org_id,
        "pending_approval_count": pending_approval_count,
        **_build_ui_language_context(request, user),
    })


@router.get("/manual")
async def manual_page(
    request: Request,
    org_id: int = None,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    if not user:
        return RedirectResponse(url="/auth/login", status_code=303)

    effective_org_id = await get_org_id_for_user(session, user, org_id)
    membership = (
        await session.exec(
            select(Membership).where(
                and_(
                    Membership.org_id == effective_org_id,
                    Membership.user_id == user.id,
                )
            )
        )
    ).first()
    if not membership:
        return RedirectResponse(url="/dashboard", status_code=303)

    onboarding = await onboarding_service.get_status(
        session=session,
        org_id=effective_org_id,
        user_id=user.id,
    )
    pending_approval_count = await _get_pending_approval_count(session, effective_org_id)
    return templates.TemplateResponse(
        "pages/manual.html",
        {
            "request": request,
            "active_page": "manual",
            "user": user,
            "org_id": effective_org_id,
            "pending_approval_count": pending_approval_count,
            "onboarding": onboarding,
            **_build_ui_language_context(request, user),
        },
    )


@router.get("/manual/execution-board")
async def execution_board_page(
    request: Request,
    org_id: int = None,
    period_days: int = 30,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    if not user:
        return RedirectResponse(url="/auth/login", status_code=303)

    effective_org_id = await get_org_id_for_user(session, user, org_id)
    membership = (
        await session.exec(
            select(Membership).where(
                and_(
                    Membership.org_id == effective_org_id,
                    Membership.user_id == user.id,
                )
            )
        )
    ).first()
    if not membership:
        return RedirectResponse(url="/dashboard", status_code=303)

    pending_approval_count = await _get_pending_approval_count(session, effective_org_id)
    onboarding = await onboarding_service.get_status(
        session=session,
        org_id=effective_org_id,
        user_id=user.id,
    )
    proof_overview = await proof_service.compute_overview(
        session=session,
        org_id=effective_org_id,
        period_days=period_days,
    )
    daily_summary = await report_service.build_daily_summary(
        session=session,
        org_id=effective_org_id,
        day_str=None,
    )

    measured_stats = [
        {
            "label": "연결된 사이트 수",
            "value": str(daily_summary.get("site_count", 0)),
            "evidence": "measured",
            "note": "일일 리포트 요약",
        },
        {
            "label": "답변 점유율(ACR)",
            "value": f"{proof_overview.get('answer_capture_rate_pct', 0.0)}%",
            "evidence": "measured",
            "note": f"최근 {proof_overview.get('period_days', period_days)}일",
        },
        {
            "label": "인용률",
            "value": f"{proof_overview.get('citation_rate_pct', 0.0)}%",
            "evidence": "measured",
            "note": f"최근 {proof_overview.get('period_days', period_days)}일",
        },
        {
            "label": "AI 기여 전환율",
            "value": f"{proof_overview.get('ai_assist_rate_pct', 0.0)}%",
            "evidence": "measured",
            "note": f"신뢰도: {proof_overview.get('confidence_level', 'low')}",
        },
    ]

    projected_stats = [
        {
            "metric": "첫 증명 도달 시간",
            "current": "3일 (수동 운영 기준)",
            "target": "30분",
            "impact": "최대 94% 단축",
            "evidence": "predicted",
        },
        {
            "metric": "온보딩 단계 완료율",
            "current": "단일 진입 흐름",
            "target": "가이드형 7단계 흐름",
            "impact": "+20% ~ +35%",
            "evidence": "predicted",
        },
        {
            "metric": "액션-성과 전환율",
            "current": "수동 관찰",
            "target": "예약 자동 평가",
            "impact": "+15% ~ +28%",
            "evidence": "predicted",
        },
        {
            "metric": "경영 보고 처리속도",
            "current": "수동 취합",
            "target": "일일 자동 PDF + 보드",
            "impact": "4배 ~ 6배 향상",
            "evidence": "predicted",
        },
    ]

    execution_backlog = [
        {
            "priority": "P0",
            "title": "모든 KPI 카드에 증명 신뢰도 배지 적용",
            "scope": "대시보드/리포트/프루프 카드에 표본 기반 신뢰도를 노출.",
            "files": "app/templates/pages/proof.html, app/templates/pages/dashboard.html, app/services/proof_service.py",
            "estimate": "0.5 day",
            "status": "completed",
        },
        {
            "priority": "P0",
            "title": "실측/예측 영향 라벨 전면 분리",
            "scope": "개선 주장과 내보내기 payload에 증거 라벨을 강제.",
            "files": "app/routers/pages.py, app/templates/pages/report.html, app/services/report_service.py",
            "estimate": "0.5 day",
            "status": "completed",
        },
        {
            "priority": "P1",
            "title": "액션 후 자동 보상 평가",
            "scope": "적용 전/후 스냅샷을 비교해 밴딧 보상값을 자동 반영.",
            "files": "app/services/optimization_service.py, app/services/bandit_service.py",
            "estimate": "1.5 days",
            "status": "completed",
        },
        {
            "priority": "P1",
            "title": "고객 신뢰 내러티브 위젯",
            "scope": "왜 지표가 변했는지, 어떤 액션이 결과를 만들었는지 설명.",
            "files": "app/templates/pages/proof.html, app/templates/pages/daily_reports.html",
            "estimate": "1.0 day",
            "status": "completed",
        },
        {
            "priority": "P2",
            "title": "공개 상태/변경이력 피드",
            "scope": "신뢰성 업데이트와 릴리스 노트를 footer 경로에 게시.",
            "files": "app/templates/pages/footer_detail.html, docs/",
            "estimate": "1.0 day",
            "status": "completed",
        },
    ]

    readiness_checklist = [
        {
            "item": "ACR/인용률/AI 기여 지표 스키마가 이미 준비되어 있음.",
            "status": "ready",
        },
        {
            "item": "온보딩 흐름과 매뉴얼이 구현되어 확장 가능.",
            "status": "ready",
        },
        {
            "item": "결제 및 승인 거버넌스가 운영 가능 상태.",
            "status": "ready",
        },
        {
            "item": "자동 보상 계산이 baseline/post 스냅샷 델타 방식으로 동작.",
            "status": "ready",
        },
        {
            "item": "공개 changelog/status 피드가 게시되어 고객에게 노출됨.",
            "status": "ready",
        },
    ]

    return templates.TemplateResponse(
        "pages/execution_board.html",
        {
            "request": request,
            "active_page": "manual",
            "user": user,
            "org_id": effective_org_id,
            "pending_approval_count": pending_approval_count,
            "onboarding": onboarding,
            "proof_overview": proof_overview,
            "measured_stats": measured_stats,
            "projected_stats": projected_stats,
            "execution_backlog": execution_backlog,
            "readiness_checklist": readiness_checklist,
            **_build_ui_language_context(request, user),
        },
    )


@router.get("/reports/daily")
async def daily_reports_page(
    request: Request,
    org_id: int = None,
    date: str | None = None,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    if not user:
        return RedirectResponse(url="/auth/login", status_code=303)

    effective_org_id = await get_org_id_for_user(session, user, org_id)
    membership = (
        await session.exec(
            select(Membership).where(
                and_(
                    Membership.org_id == effective_org_id,
                    Membership.user_id == user.id,
                )
            )
        )
    ).first()
    if not membership:
        return RedirectResponse(url="/dashboard", status_code=303)

    summary = await report_service.build_daily_summary(
        session=session,
        org_id=effective_org_id,
        day_str=date,
    )
    pending_approval_count = await _get_pending_approval_count(session, effective_org_id)
    return templates.TemplateResponse(
        "pages/daily_reports.html",
        {
            "request": request,
            "active_page": "reports",
            "user": user,
            "org_id": effective_org_id,
            "pending_approval_count": pending_approval_count,
            "summary": summary,
            **_build_ui_language_context(request, user),
        },
    )


@router.get("/proof")
async def proof_page(
    request: Request,
    org_id: int = None,
    query_set_id: Optional[int] = None,
    period_days: int = 30,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    if not user:
        return RedirectResponse(url="/auth/login", status_code=303)

    effective_org_id = await get_org_id_for_user(session, user, org_id)
    membership = (
        await session.exec(
            select(Membership).where(
                and_(
                    Membership.org_id == effective_org_id,
                    Membership.user_id == user.id,
                )
            )
        )
    ).first()
    if not membership:
        return RedirectResponse(url="/dashboard", status_code=303)

    pending_approval_count = await _get_pending_approval_count(session, effective_org_id)
    overview = await proof_service.compute_overview(
        session=session,
        org_id=effective_org_id,
        period_days=period_days,
    )
    query_sets = await innovation_service.list_query_sets(session, effective_org_id)
    available_query_set_ids = {row.id for row in query_sets if row.id is not None}
    selected_query_set_id = query_set_id if query_set_id in available_query_set_ids else None
    if selected_query_set_id is None and query_sets:
        selected_query_set_id = query_sets[0].id

    before_after = await proof_service.compute_before_after(
        session=session,
        org_id=effective_org_id,
        query_set_id=selected_query_set_id,
    )
    optimization_impact = await optimization_service.build_action_impact_summary(
        session=session,
        org_id=effective_org_id,
        limit=4,
    )
    snapshots = await proof_service.list_snapshots(
        session=session,
        org_id=effective_org_id,
        limit=6,
    )
    onboarding = await onboarding_service.get_status(
        session=session,
        org_id=effective_org_id,
        user_id=user.id,
    )
    subscription_info = await subscription_service.get_subscription_with_org(
        session,
        effective_org_id,
    )
    current_plan_code = (
        subscription_info["subscription"].plan_code
        if subscription_info.get("subscription")
        else "free"
    )
    plan_value_ladder = _build_plan_value_ladder(current_plan_code)

    return templates.TemplateResponse(
        "pages/proof.html",
        {
            "request": request,
            "active_page": "proof",
            "user": user,
            "org_id": effective_org_id,
            "membership_role": membership.role,
            "pending_approval_count": pending_approval_count,
            "overview": overview,
            "query_sets": query_sets,
            "selected_query_set_id": selected_query_set_id,
            "before_after": before_after,
            "optimization_impact": optimization_impact,
            "snapshots": snapshots,
            "onboarding": onboarding,
            "subscription": subscription_info,
            "plan_value_ladder": plan_value_ladder,
            **_build_ui_language_context(request, user),
        },
    )


@router.get("/approvals")
async def approvals_page(
    request: Request,
    org_id: int = None,
    status: str = "all",
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    try:
        if not user:
            return RedirectResponse(url="/auth/login", status_code=303)

        effective_org_id = await get_org_id_for_user(session, user, org_id)
        membership = (
            await session.exec(
                select(Membership).where(
                    and_(
                        Membership.org_id == effective_org_id,
                        Membership.user_id == user.id,
                    )
                )
            )
        ).first()
        if not membership:
            return RedirectResponse(url="/dashboard", status_code=303)

        organization = (
            await session.exec(select(Organization).where(Organization.id == effective_org_id))
        ).first()

        pending_approval_count = await _get_pending_approval_count(session, effective_org_id)
        status_counts = await _get_approval_status_counts(session, effective_org_id)

        # Filter is handled by approval_service.list_requests, passing 'status' if not 'all'
        filter_status = None if status == "all" else status
        approval_rows = await approval_service.list_requests(
            session=session,
            org_id=effective_org_id,
            status=filter_status,
        )
        serialized_approvals = await _serialize_approvals_for_ui(session, approval_rows)

        return templates.TemplateResponse(
            "pages/approvals.html",
            {
                "request": request,
                "active_page": "approvals",
                "user": user,
                "org_id": effective_org_id,
                "organization": organization,
                "membership_role": membership.role,
                "pending_approval_count": pending_approval_count,
                "status_counts": status_counts,
                "approvals": serialized_approvals,
                "status_filter": status,
                "can_review_approvals": membership.role in {"owner", "admin"},
                **_build_ui_language_context(request, user),
            },
        )
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        logger.error(f"CRITICAL ERROR in approvals_page: {e}\n{error_trace}")
        raise e


@router.get("/billing")
async def billing_page(
    request: Request,
    org_id: int = None,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    if not user:
        return RedirectResponse(url="/auth/login", status_code=303)

    effective_org_id = await get_org_id_for_user(session, user, org_id)
    membership = (
        await session.exec(
            select(Membership).where(
                and_(
                    Membership.org_id == effective_org_id,
                    Membership.user_id == user.id,
                )
            )
        )
    ).first()
    if not membership:
        return RedirectResponse(url="/dashboard", status_code=303)

    subscription_info = await subscription_service.get_subscription_with_org(
        session, effective_org_id
    )
    
    # Enhance subscription info with upcoming invoice if configured
    if subscription_info.get("subscription") and subscription_info["subscription"].stripe_customer_id:
         upcoming = await subscription_service.get_upcoming_invoice(session, effective_org_id)
         subscription_info["upcoming_invoice"] = upcoming

    pending_approval_count = await _get_pending_approval_count(session, effective_org_id)

    return templates.TemplateResponse(
        "pages/billing.html",
        {
            "request": request,
            "active_page": "billing",
            "user": user,
            "org_id": effective_org_id,
            "can_manage_billing": membership.role in {"owner", "admin"},
            "subscription": subscription_info,
            "pending_approval_count": pending_approval_count,
            **_build_ui_language_context(request, user),
        },
    )


@router.get("/admin")
async def admin_page(
    request: Request,
    org_id: int = None,
    q: str = "",
    limit: int = 100,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    if not user:
        return RedirectResponse(url="/auth/login", status_code=303)

    bounded_limit = min(max(int(limit or 100), 20), 300)
    search_term = (q or "").strip().lower()
    like_pattern = f"%{search_term}%"
    scoped_org_id: Optional[int] = None

    if not user.is_superuser:
        try:
            scoped_org_id = await get_org_id_for_user(session, user, org_id)
        except HTTPException as exc:
            logger.info("Admin page denied for user_id=%s: %s", user.id, exc.detail)
            raise HTTPException(status_code=403, detail="Admin access required")
        membership = (
            await session.exec(
                select(Membership).where(
                    and_(
                        Membership.org_id == scoped_org_id,
                        Membership.user_id == user.id,
                    )
                )
            )
        ).first()
        if not membership or membership.role not in {"owner", "admin"}:
            raise HTTPException(status_code=403, detail="Admin access required")

    org_query = select(Organization).order_by(Organization.updated_at.desc()).limit(bounded_limit)
    if scoped_org_id is not None:
        org_query = org_query.where(Organization.id == scoped_org_id)
    if search_term:
        org_query = org_query.where(
            or_(
                func.lower(Organization.name).like(like_pattern),
                func.lower(Organization.slug).like(like_pattern),
                func.lower(func.coalesce(Organization.billing_email, "")).like(like_pattern),
            )
        )
    org_rows = (await session.exec(org_query)).all()
    org_ids = [row.id for row in org_rows if row.id is not None]

    subscriptions_by_org: dict[int, Subscription] = {}
    owner_email_by_org: dict[int, str] = {}
    member_count_by_org: dict[int, int] = {}
    site_count_by_org: dict[int, int] = {}
    latest_invoice_by_org: dict[int, Invoice] = {}

    if org_ids:
        subscription_rows = (
            await session.exec(select(Subscription).where(Subscription.org_id.in_(org_ids)))
        ).all()
        subscriptions_by_org = {row.org_id: row for row in subscription_rows}

        owner_rows = (
            await session.exec(
                select(Membership.org_id, User.email)
                .join(User, User.id == Membership.user_id)
                .where(
                    and_(
                        Membership.org_id.in_(org_ids),
                        Membership.role == "owner",
                    )
                )
            )
        ).all()
        for org_id_value, owner_email in owner_rows:
            if org_id_value not in owner_email_by_org:
                owner_email_by_org[int(org_id_value)] = str(owner_email or "")

        member_counts = (
            await session.exec(
                select(Membership.org_id, func.count(Membership.user_id))
                .where(Membership.org_id.in_(org_ids))
                .group_by(Membership.org_id)
            )
        ).all()
        member_count_by_org = {int(org_id_value): int(count or 0) for org_id_value, count in member_counts}

        site_counts = (
            await session.exec(
                select(Site.org_id, func.count(Site.id))
                .where(Site.org_id.in_(org_ids))
                .group_by(Site.org_id)
            )
        ).all()
        site_count_by_org = {int(org_id_value): int(count or 0) for org_id_value, count in site_counts}

        invoice_rows = (
            await session.exec(
                select(Invoice)
                .where(Invoice.org_id.in_(org_ids))
                .order_by(Invoice.created_at.desc())
                .limit(max(200, bounded_limit))
            )
        ).all()
        for invoice in invoice_rows:
            if invoice.org_id not in latest_invoice_by_org:
                latest_invoice_by_org[invoice.org_id] = invoice

    org_crm_rows: list[dict[str, Any]] = []
    for organization in org_rows:
        if organization.id is None:
            continue
        subscription = subscriptions_by_org.get(organization.id)
        latest_invoice = latest_invoice_by_org.get(organization.id)
        org_crm_rows.append(
            {
                "org_id": organization.id,
                "name": organization.name,
                "slug": organization.slug,
                "billing_email": organization.billing_email,
                "owner_email": owner_email_by_org.get(organization.id),
                "members": member_count_by_org.get(organization.id, 0),
                "sites": site_count_by_org.get(organization.id, 0),
                "plan_code": subscription.plan_code if subscription else "free",
                "status": (
                    subscription.status.value
                    if subscription and hasattr(subscription.status, "value")
                    else (str(subscription.status) if subscription else "inactive")
                ),
                "stripe_customer_id": subscription.stripe_customer_id if subscription else None,
                "stripe_subscription_id": subscription.stripe_subscription_id if subscription else None,
                "cancel_at_period_end": subscription.cancel_at_period_end if subscription else False,
                "current_period_end": subscription.current_period_end if subscription else None,
                "latest_invoice_total": latest_invoice.total if latest_invoice else None,
                "latest_invoice_currency": latest_invoice.currency if latest_invoice else None,
                "latest_invoice_status": latest_invoice.status if latest_invoice else None,
                "latest_invoice_at": latest_invoice.created_at if latest_invoice else None,
            }
        )

    if scoped_org_id is not None:
        user_query = (
            select(User)
            .join(Membership, Membership.user_id == User.id)
            .where(Membership.org_id == scoped_org_id)
        )
    else:
        user_query = select(User)

    if search_term:
        user_query = user_query.where(
            or_(
                func.lower(User.email).like(like_pattern),
                func.lower(func.coalesce(User.full_name, "")).like(like_pattern),
            )
        )
    user_query = user_query.order_by(User.updated_at.desc()).limit(bounded_limit)
    user_rows = (await session.exec(user_query)).all()
    user_ids = [row.id for row in user_rows if row.id is not None]

    membership_count_by_user: dict[int, int] = {}
    org_names_by_user: dict[int, list[str]] = {}
    if user_ids:
        membership_counts = (
            await session.exec(
                select(Membership.user_id, func.count(Membership.org_id))
                .where(Membership.user_id.in_(user_ids))
                .group_by(Membership.user_id)
            )
        ).all()
        membership_count_by_user = {
            int(user_id_value): int(count or 0) for user_id_value, count in membership_counts
        }

        membership_org_rows = (
            await session.exec(
                select(Membership.user_id, Organization.slug)
                .join(Organization, Organization.id == Membership.org_id)
                .where(Membership.user_id.in_(user_ids))
            )
        ).all()
        for user_id_value, org_slug in membership_org_rows:
            key = int(user_id_value)
            org_names_by_user.setdefault(key, [])
            if len(org_names_by_user[key]) < 4:
                org_names_by_user[key].append(str(org_slug or ""))

    user_crm_rows: list[dict[str, Any]] = []
    for row in user_rows:
        if row.id is None:
            continue
        user_crm_rows.append(
            {
                "user_id": row.id,
                "email": row.email,
                "full_name": row.full_name,
                "is_active": row.is_active,
                "is_superuser": row.is_superuser,
                "created_at": row.created_at,
                "updated_at": row.updated_at,
                "last_login_at": row.last_login_at,
                "org_count": membership_count_by_user.get(row.id, 0),
                "org_slugs": org_names_by_user.get(row.id, []),
            }
        )

    return templates.TemplateResponse(
        "pages/admin.html",
        {
            "request": request,
            "active_page": "admin",
            "user": user,
            "org_id": scoped_org_id,
            "pending_approval_count": 0,
            "search_query": q,
            "result_limit": bounded_limit,
            "org_crm_rows": org_crm_rows,
            "user_crm_rows": user_crm_rows,
            **_build_ui_language_context(request, user),
        },
    )


@router.get("/docs/integration-guide")
async def integration_guide_page(
    request: Request,
    org_id: int = None,
    site_id: Optional[int] = None,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    if not user:
        return RedirectResponse(url="/auth/login", status_code=303)

    effective_org_id = await get_org_id_for_user(session, user, org_id)
    membership = (
        await session.exec(
            select(Membership).where(
                and_(
                    Membership.org_id == effective_org_id,
                    Membership.user_id == user.id,
                )
            )
        )
    ).first()
    if not membership:
        return RedirectResponse(url="/dashboard", status_code=303)

    target_site = None
    if site_id is not None:
        target_site = (
            await session.exec(
                select(Site).where(
                    and_(
                        Site.id == site_id,
                        Site.org_id == effective_org_id,
                    )
                )
            )
        ).first()
    if target_site is None:
        target_site = (
            await session.exec(
                select(Site)
                .where(Site.org_id == effective_org_id)
                .order_by(Site.created_at.desc())
            )
        ).first()

    bridge_script_url = None
    installation_status = {
        "detected": False,
        "script_request_count_7d": 0,
        "bridge_event_count_7d": 0,
        "raw_event_total_7d": 0,
        "raw_event_dropped_7d": 0,
        "raw_event_accept_rate_pct_7d": None,
        "batch_source_share_pct_7d": None,
        "raw_event_retry_seen_7d": 0,
        "raw_event_retry_seen_share_pct_7d": None,
        "raw_event_retry_pending_7d": 0,
        "raw_event_retry_exhausted_7d": 0,
    }
    if target_site:
        seven_days_ago = datetime.utcnow() - timedelta(days=7)
        script_request_count_7d = int(
            (
                await session.exec(
                    select(func.count()).select_from(BotVisit).where(
                        and_(
                            BotVisit.site_id == target_site.id,
                            BotVisit.timestamp >= seven_days_ago,
                        )
                    )
                )
            ).one()
            or 0
        )
        bridge_event_count_7d = int(
            (
                await session.exec(
                    select(func.count()).select_from(BridgeEvent).where(
                        and_(
                            BridgeEvent.site_id == target_site.id,
                            BridgeEvent.timestamp >= seven_days_ago,
                        )
                    )
                )
            ).one()
            or 0
        )
        raw_event_total_7d = int(
            (
                await session.exec(
                    select(func.count()).select_from(BridgeEventRaw).where(
                        and_(
                            BridgeEventRaw.site_id == target_site.id,
                            BridgeEventRaw.created_at >= seven_days_ago,
                        )
                    )
                )
            ).one()
            or 0
        )
        raw_event_dropped_7d = int(
            (
                await session.exec(
                    select(func.count()).select_from(BridgeEventRaw).where(
                        and_(
                            BridgeEventRaw.site_id == target_site.id,
                            BridgeEventRaw.created_at >= seven_days_ago,
                            BridgeEventRaw.dropped_reason.is_not(None),
                        )
                    )
                )
            ).one()
            or 0
        )
        raw_event_batch_source_7d = int(
            (
                await session.exec(
                    select(func.count()).select_from(BridgeEventRaw).where(
                        and_(
                            BridgeEventRaw.site_id == target_site.id,
                            BridgeEventRaw.created_at >= seven_days_ago,
                            BridgeEventRaw.ingest_source == "batch_post",
                        )
                    )
                )
            ).one()
            or 0
        )
        raw_event_retry_seen_7d = int(
            (
                await session.exec(
                    select(func.count()).select_from(BridgeEventRaw).where(
                        and_(
                            BridgeEventRaw.site_id == target_site.id,
                            BridgeEventRaw.created_at >= seven_days_ago,
                            BridgeEventRaw.retry_count > 0,
                        )
                    )
                )
            ).one()
            or 0
        )
        raw_event_retry_pending_7d = int(
            (
                await session.exec(
                    select(func.count()).select_from(BridgeEventRaw).where(
                        and_(
                            BridgeEventRaw.site_id == target_site.id,
                            BridgeEventRaw.created_at >= seven_days_ago,
                            BridgeEventRaw.normalized == False,  # noqa: E712
                            BridgeEventRaw.dropped_reason.is_(None),
                        )
                    )
                )
            ).one()
            or 0
        )
        raw_event_retry_exhausted_7d = int(
            (
                await session.exec(
                    select(func.count()).select_from(BridgeEventRaw).where(
                        and_(
                            BridgeEventRaw.site_id == target_site.id,
                            BridgeEventRaw.created_at >= seven_days_ago,
                            BridgeEventRaw.dropped_reason == "retry_exhausted",
                        )
                    )
                )
            ).one()
            or 0
        )
        raw_event_accept_rate_pct_7d = (
            round(
                ((raw_event_total_7d - raw_event_dropped_7d) / raw_event_total_7d) * 100.0,
                1,
            )
            if raw_event_total_7d > 0
            else None
        )
        raw_event_retry_seen_share_pct_7d = (
            round((raw_event_retry_seen_7d / raw_event_total_7d) * 100.0, 1)
            if raw_event_total_7d > 0
            else None
        )
        batch_source_share_pct_7d = (
            round((raw_event_batch_source_7d / raw_event_total_7d) * 100.0, 1)
            if raw_event_total_7d > 0
            else None
        )
        installation_status = {
            "detected": (script_request_count_7d + bridge_event_count_7d) > 0,
            "script_request_count_7d": script_request_count_7d,
            "bridge_event_count_7d": bridge_event_count_7d,
            "raw_event_total_7d": raw_event_total_7d,
            "raw_event_dropped_7d": raw_event_dropped_7d,
            "raw_event_accept_rate_pct_7d": raw_event_accept_rate_pct_7d,
            "batch_source_share_pct_7d": batch_source_share_pct_7d,
            "raw_event_retry_seen_7d": raw_event_retry_seen_7d,
            "raw_event_retry_seen_share_pct_7d": raw_event_retry_seen_share_pct_7d,
            "raw_event_retry_pending_7d": raw_event_retry_pending_7d,
            "raw_event_retry_exhausted_7d": raw_event_retry_exhausted_7d,
        }
        bridge_script_url = str(request.base_url).rstrip("/") + f"/api/bridge/{target_site.script_id}.js"

    pending_approval_count = await _get_pending_approval_count(session, effective_org_id)
    return templates.TemplateResponse(
        "pages/integration_guide.html",
        {
            "request": request,
            "active_page": "proof",
            "user": user,
            "org_id": effective_org_id,
            "pending_approval_count": pending_approval_count,
            "site": target_site,
            "bridge_script_url": bridge_script_url,
            "installation_status": installation_status,
            **_build_ui_language_context(request, user),
        },
    )

@router.get("/features")
async def features_page(
    request: Request, 
    user: Optional[User] = Depends(get_current_user)
):
    return templates.TemplateResponse("pages/features.html", {
        "request": request, 
        "active_page": "features", 
        "user": user,
        **_build_ui_language_context(request, user),
    })


@router.get("/footer/{slug}")
async def footer_detail_page(
    request: Request,
    slug: str,
    user: Optional[User] = Depends(get_current_user),
):
    normalized_slug = (slug or "").strip().lower()
    page_detail = FOOTER_PAGE_DETAILS.get(normalized_slug)
    if not page_detail:
        raise HTTPException(status_code=404, detail="Footer page not found")

    return templates.TemplateResponse(
        "pages/footer_detail.html",
        {
            "request": request,
            "active_page": "footer",
            "user": user,
            "footer_page": {**page_detail, "slug": normalized_slug},
            "footer_nav_items": FOOTER_NAV_ITEMS,
            **_build_ui_language_context(request, user),
        },
    )

@router.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return RedirectResponse(url="/static/favicon.svg")
