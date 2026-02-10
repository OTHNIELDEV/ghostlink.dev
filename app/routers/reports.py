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
    evidence = summary.get("evidence", {})
    proof_evidence = evidence.get("proof", {}) if isinstance(evidence, dict) else {}
    attribution_evidence = evidence.get("attribution", {}) if isinstance(evidence, dict) else {}

    lines: list[str] = [
        f"Organization: {summary['org_name']} (id: {summary['org_id']})",
        f"Report Date: {summary['report_date']}",
        "",
        "1) Activation & Ops",
        f"- Active Sites [{str(evidence.get('site_count', 'measured')).upper()}]: {summary['site_count']}",
        f"- Avg Visibility Score [{str(evidence.get('avg_visibility_score', 'predicted')).upper()}]: {summary['avg_visibility_score']}",
        f"- Pending Approvals [{str(evidence.get('pending_approvals', 'measured')).upper()}]: {summary['pending_approvals']}",
        "",
        "2) Integration Signals",
        f"- AI Crawler Visits [{str(evidence.get('ai_crawler_visits', 'measured')).upper()}]: {summary['ai_crawler_visits']}",
        f"- Human Visits [{str(evidence.get('human_visits', 'measured')).upper()}]: {summary['human_visits']}",
        f"- Bridge Events [{str(evidence.get('bridge_event_count', 'measured')).upper()}]: {summary['bridge_event_count']}",
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
            f"- Runs Completed [{str(proof_evidence.get('run_count', 'measured')).upper()}]: {proof['run_count']}",
            f"- Queries Scored [{str(proof_evidence.get('total_queries_scored', 'measured')).upper()}]: {proof['total_queries_scored']}",
            f"- Answer Capture Rate [{str(proof_evidence.get('answer_capture_rate_pct', 'measured')).upper()}]: {proof['answer_capture_rate_pct']}%",
            f"- Citation Rate [{str(proof_evidence.get('citation_rate_pct', 'measured')).upper()}]: {proof['citation_rate_pct']}%",
            f"- Avg Quality Score [{str(proof_evidence.get('average_quality_score', 'measured')).upper()}]: {proof['average_quality_score']}",
            f"- Proof Confidence: {proof.get('confidence_level', 'low')} (sample {proof.get('sample_size', 0)})",
        ]
    )

    attribution = summary["attribution"]
    lines.extend(
        [
            "",
            "4) Attribution",
            f"- Total Events [{str(attribution_evidence.get('total_events', 'measured')).upper()}]: {attribution['total_events']}",
            f"- Conversions [{str(attribution_evidence.get('conversions_total', 'measured')).upper()}]: {attribution['conversions_total']}",
            f"- AI Assisted Conversions [{str(attribution_evidence.get('ai_assisted_conversions', 'measured')).upper()}]: {attribution['ai_assisted_conversions']}",
            f"- AI Assist Rate [{str(attribution_evidence.get('ai_assist_rate_pct', 'measured')).upper()}]: {attribution['ai_assist_rate_pct']}%",
            f"- Attribution Confidence: {attribution.get('confidence_level', 'low')}",
            "",
            "5) Optimization Impact Narrative",
        ]
    )
    optimization_impact = summary.get("optimization_impact", {})
    impact_items = optimization_impact.get("items", []) if isinstance(optimization_impact, dict) else []
    impact_totals = optimization_impact.get("totals", {}) if isinstance(optimization_impact, dict) else {}
    lines.append(
        "- Totals [MEASURED]: "
        f"measured={impact_totals.get('measured_count', 0)}, "
        f"pending={impact_totals.get('pending_count', 0)}, "
        f"positive_lift={impact_totals.get('positive_count', 0)}"
    )
    if impact_items:
        for row in impact_items[:8]:
            evidence_type = str(row.get("evidence_type", "predicted")).upper()
            lines.append(f"- [{evidence_type}] {row.get('title', 'Untitled action')}")
            lines.append(f"  * {row.get('narrative', '-')}")
            if row.get("evidence_type") == "measured":
                delta = float(row.get("delta_proof_score", 0.0))
                lines.append(
                    f"  * Delta: {'+' if delta >= 0 else ''}{delta} "
                    f"| Reward: {row.get('reward', 0.0)} "
                    f"| Confidence: {row.get('confidence_level', 'low')}"
                )
    else:
        lines.append("- No evaluated optimization narratives yet.")

    lines.extend(["", "6) Site Inventory"])
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
