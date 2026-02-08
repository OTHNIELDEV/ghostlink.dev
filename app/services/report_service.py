from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from sqlmodel import and_, func, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.analytics import BotVisit, BridgeEvent
from app.models.approval import ApprovalRequest
from app.models.innovation import AnswerCaptureResult, AnswerCaptureRun, AttributionEvent
from app.models.organization import Organization
from app.models.site import Site
from app.services.innovation_service import innovation_service


class ReportService:
    def _day_window(self, day_str: str | None) -> tuple[datetime, datetime]:
        if day_str:
            try:
                day = datetime.strptime(day_str, "%Y-%m-%d")
            except ValueError:
                day = datetime.utcnow()
        else:
            day = datetime.utcnow()
        start = day.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
        return start, end

    async def build_daily_summary(
        self,
        session: AsyncSession,
        org_id: int,
        day_str: str | None = None,
    ) -> dict[str, Any]:
        day_start, day_end = self._day_window(day_str)
        org = await session.get(Organization, org_id)
        org_name = org.name if org else f"Org {org_id}"

        sites = (
            await session.exec(
                select(Site).where(Site.org_id == org_id).order_by(Site.created_at.desc())
            )
        ).all()
        site_ids = [row.id for row in sites if row.id is not None]

        bot_rows = []
        bridge_rows = []
        if site_ids:
            bot_rows = (
                await session.exec(
                    select(BotVisit).where(
                        and_(
                            BotVisit.site_id.in_(site_ids),
                            BotVisit.timestamp >= day_start,
                            BotVisit.timestamp < day_end,
                        )
                    )
                )
            ).all()
            bridge_rows = (
                await session.exec(
                    select(BridgeEvent).where(
                        and_(
                            BridgeEvent.site_id.in_(site_ids),
                            BridgeEvent.timestamp >= day_start,
                            BridgeEvent.timestamp < day_end,
                        )
                    )
                )
            ).all()

        ai_crawler_visits = len([row for row in bot_rows if row.bot_name != "Human/Browser"])
        human_visits = len([row for row in bot_rows if row.bot_name == "Human/Browser"])
        bridge_event_count = len(bridge_rows)

        by_bot: dict[str, int] = defaultdict(int)
        for row in bot_rows:
            if row.bot_name != "Human/Browser":
                by_bot[row.bot_name] += 1
        top_bots = sorted(
            [{"name": name, "count": count} for name, count in by_bot.items()],
            key=lambda x: x["count"],
            reverse=True,
        )[:8]

        avg_score = (
            round(sum(int(row.ai_score or 0) for row in sites) / len(sites), 1)
            if sites
            else 0.0
        )

        run_rows = (
            await session.exec(
                select(AnswerCaptureRun).where(
                    and_(
                        AnswerCaptureRun.org_id == org_id,
                        AnswerCaptureRun.status == "completed",
                        AnswerCaptureRun.completed_at >= day_start,
                        AnswerCaptureRun.completed_at < day_end,
                    )
                )
            )
        ).all()
        run_ids = [row.id for row in run_rows if row.id is not None]
        result_rows = []
        if run_ids:
            result_rows = (
                await session.exec(
                    select(AnswerCaptureResult).where(AnswerCaptureResult.run_id.in_(run_ids))
                )
            ).all()

        total_queries_scored = len(result_rows)
        brand_mentions = len([row for row in result_rows if row.has_brand_mention])
        citations = len([row for row in result_rows if row.has_site_citation])
        avg_quality = (
            round(sum(float(row.quality_score or 0.0) for row in result_rows) / total_queries_scored, 1)
            if total_queries_scored > 0
            else 0.0
        )
        acr = round((brand_mentions / total_queries_scored) * 100.0, 1) if total_queries_scored > 0 else 0.0
        citation_rate = round((citations / total_queries_scored) * 100.0, 1) if total_queries_scored > 0 else 0.0

        attribution_rows = (
            await session.exec(
                select(AttributionEvent).where(
                    and_(
                        AttributionEvent.org_id == org_id,
                        AttributionEvent.event_timestamp >= day_start,
                        AttributionEvent.event_timestamp < day_end,
                    )
                )
            )
        ).all()
        conversions = [row for row in attribution_rows if row.event_name in innovation_service.CONVERSION_EVENTS]
        conversion_sessions = {row.session_key for row in conversions if row.session_key}
        ai_sessions = {row.session_key for row in attribution_rows if row.source_type == "ai" and row.session_key}
        ai_assisted = conversion_sessions.intersection(ai_sessions)
        conversions_total = len(conversions)
        ai_assisted_total = len(ai_assisted)
        ai_assist_rate = (
            round((ai_assisted_total / conversions_total) * 100.0, 1) if conversions_total > 0 else 0.0
        )

        pending_approvals = int(
            (
                await session.exec(
                    select(func.count())
                    .select_from(ApprovalRequest)
                    .where(
                        and_(
                            ApprovalRequest.org_id == org_id,
                            ApprovalRequest.status == "pending",
                        )
                    )
                )
            ).one()
            or 0
        )

        return {
            "org_id": org_id,
            "org_name": org_name,
            "report_date": day_start.strftime("%Y-%m-%d"),
            "generated_at": datetime.utcnow(),
            "window_start": day_start,
            "window_end": day_end,
            "site_count": len(sites),
            "avg_visibility_score": avg_score,
            "ai_crawler_visits": ai_crawler_visits,
            "human_visits": human_visits,
            "bridge_event_count": bridge_event_count,
            "top_bots": top_bots,
            "proof": {
                "run_count": len(run_rows),
                "total_queries_scored": total_queries_scored,
                "answer_capture_rate_pct": acr,
                "citation_rate_pct": citation_rate,
                "average_quality_score": avg_quality,
            },
            "attribution": {
                "total_events": len(attribution_rows),
                "conversions_total": conversions_total,
                "ai_assisted_conversions": ai_assisted_total,
                "ai_assist_rate_pct": ai_assist_rate,
            },
            "pending_approvals": pending_approvals,
            "sites": [
                {
                    "id": row.id,
                    "url": row.url,
                    "status": row.status,
                    "ai_score": int(row.ai_score or 0),
                    "schema_type": row.schema_type,
                    "updated_at": row.updated_at,
                }
                for row in sites
            ],
        }


report_service = ReportService()
