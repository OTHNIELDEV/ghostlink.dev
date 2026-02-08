from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.rbac import require_org_membership, resolve_org_id_from_request
from app.db.engine import get_session
from app.models.user import User
from app.routers.users import get_current_user
from app.services.pdf_service import pdf_service
from app.services.report_service import report_service


router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/daily")
async def get_daily_report_json(
    request: Request,
    date: str | None = Query(default=None, description="YYYY-MM-DD"),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    org_id = await resolve_org_id_from_request(request)
    await require_org_membership(session, user, org_id)
    return await report_service.build_daily_summary(
        session=session,
        org_id=org_id,
        day_str=date,
    )


@router.get("/daily.pdf")
async def download_daily_report_pdf(
    request: Request,
    date: str | None = Query(default=None, description="YYYY-MM-DD"),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    org_id = await resolve_org_id_from_request(request)
    await require_org_membership(session, user, org_id)
    summary = await report_service.build_daily_summary(
        session=session,
        org_id=org_id,
        day_str=date,
    )

    lines: list[str] = [
        f"Organization: {summary['org_name']} (id: {summary['org_id']})",
        f"Report Date: {summary['report_date']}",
        "",
        "1) Activation & Ops",
        f"- Active Sites: {summary['site_count']}",
        f"- Avg Visibility Score: {summary['avg_visibility_score']}",
        f"- Pending Approvals: {summary['pending_approvals']}",
        "",
        "2) Integration Signals",
        f"- AI Crawler Visits: {summary['ai_crawler_visits']}",
        f"- Human Visits: {summary['human_visits']}",
        f"- Bridge Events: {summary['bridge_event_count']}",
    ]

    if summary["top_bots"]:
        lines.append("- Top AI Bots:")
        for bot in summary["top_bots"]:
            lines.append(f"  * {bot['name']}: {bot['count']}")

    proof = summary["proof"]
    lines.extend(
        [
            "",
            "3) Proof KPIs",
            f"- Runs Completed: {proof['run_count']}",
            f"- Queries Scored: {proof['total_queries_scored']}",
            f"- Answer Capture Rate: {proof['answer_capture_rate_pct']}%",
            f"- Citation Rate: {proof['citation_rate_pct']}%",
            f"- Avg Quality Score: {proof['average_quality_score']}",
        ]
    )

    attribution = summary["attribution"]
    lines.extend(
        [
            "",
            "4) Attribution",
            f"- Total Events: {attribution['total_events']}",
            f"- Conversions: {attribution['conversions_total']}",
            f"- AI Assisted Conversions: {attribution['ai_assisted_conversions']}",
            f"- AI Assist Rate: {attribution['ai_assist_rate_pct']}%",
            "",
            "5) Site Inventory",
        ]
    )
    for row in summary["sites"][:30]:
        lines.append(
            f"- [{row['status']}] score {row['ai_score']} | {row['url']}"
        )
    if len(summary["sites"]) > 30:
        lines.append(f"- ... {len(summary['sites']) - 30} more sites")

    pdf_bytes = pdf_service.build_simple_report_pdf(
        title="GhostLink Daily Report",
        lines=lines,
    )
    filename = f"ghostlink-daily-report-{summary['report_date']}.pdf"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return Response(content=pdf_bytes, media_type="application/pdf", headers=headers)
