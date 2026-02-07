import logging
import json
from datetime import datetime, timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from fastapi.responses import RedirectResponse
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import func, select, and_
from app.db.engine import get_session
from app.models.approval import ApprovalRequest
from app.models.site import Site
from app.models.analytics import BotVisit
from app.models.user import User
from app.models.organization import Organization, Membership
from app.routers.users import get_current_user
from app.routers.sites import normalize_site_url, process_site_background, get_org_id_for_user
from app.services.approval_service import approval_service
from app.services.subscription_service import subscription_service
from app.services.optimization_service import optimization_service
from starlette.templating import Jinja2Templates
from typing import Any, Optional

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
logger = logging.getLogger(__name__)


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
    total = _clamp_score(scores.get("total", score))

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
            },
            {
                "title": "Answer Retrieval",
                "description": "Increases context quality for LLM answer generation.",
                "improvement": "+25%",
            },
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
        "ghostlink_impact": ghostlink_impact,
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
        
    analysis = {}
    if site.ai_analysis_json:
        try:
            analysis = json.loads(site.ai_analysis_json)
        except:
            pass
    analysis = _normalize_report_analysis(site, analysis)
            
    optimization_actions = await optimization_service.list_actions(
        session=session,
        site_id=site.id,
        org_id=effective_org_id,
        include_closed=True,
    )

    return templates.TemplateResponse("pages/report.html", {
        "request": request, 
        "site": site, 
        "analysis": analysis,
        "user": user,
        "org_id": effective_org_id,
        "optimization_actions": optimization_actions,
    })

@router.get("/")
async def landing(request: Request, user: Optional[User] = Depends(get_current_user)):
    return templates.TemplateResponse("pages/landing.html", {"request": request, "user": user})

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
        visibility_score = min(100, volume_score + diversity_score + recency_score)

        scoreboard = {
            "visibility_score": visibility_score,
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
        "organizations": organizations,
        "org_id": effective_org_id,
        "subscription": subscription_info,
        "scoreboard": scoreboard,
        "pending_approval_count": pending_approval_count,
        "pending_approvals": pending_approvals,
        "can_review_approvals": membership_role in {"owner", "admin"},
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
    })

@router.get("/billing")
async def billing_page(
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
    
    subscription_info = await subscription_service.get_subscription_with_org(
        session, effective_org_id
    )
    subscription_info["upcoming_invoice"] = None
    if subscription_info["subscription"].stripe_customer_id:
        subscription_info["upcoming_invoice"] = await subscription_service.get_upcoming_invoice(
            session, effective_org_id
        )
    
    return templates.TemplateResponse("pages/billing.html", {
        "request": request, 
        "active_page": "billing", 
        "user": user,
        "org_id": effective_org_id,
        "subscription": subscription_info,
        "pending_approval_count": pending_approval_count,
        "membership_role": membership.role,
        "can_manage_billing": membership.role in {"owner", "admin"},
    })


@router.get("/approvals")
async def approvals_page(
    request: Request,
    org_id: int = None,
    status: Optional[str] = None,
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

    requested_status = (status or "").strip().lower()
    valid_statuses = {"pending", "approved", "rejected", "failed"}
    status_filter = requested_status if requested_status in valid_statuses else None

    rows = await approval_service.list_requests(
        session=session,
        org_id=effective_org_id,
        status=status_filter,
    )
    approvals = await _serialize_approvals_for_ui(session, rows)
    status_counts = await _get_approval_status_counts(session, effective_org_id)
    pending_approval_count = status_counts["pending"]

    organization = (
        await session.exec(select(Organization).where(Organization.id == effective_org_id))
    ).first()

    return templates.TemplateResponse(
        "pages/approvals.html",
        {
            "request": request,
            "active_page": "approvals",
            "user": user,
            "org_id": effective_org_id,
            "organization": organization,
            "approvals": approvals,
            "status_filter": status_filter or "all",
            "status_counts": status_counts,
            "pending_approval_count": pending_approval_count,
            "can_review_approvals": membership.role in {"owner", "admin"},
            "membership_role": membership.role,
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
        "user": user
    })

@router.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return RedirectResponse(url="/static/favicon.svg")
