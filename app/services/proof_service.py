from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Optional

from sqlmodel import and_, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.innovation import (
    AnswerCaptureQueryItem,
    AnswerCaptureRun,
    AnswerCaptureResult,
    AttributionEvent,
    ProofSnapshot,
)
from app.services.innovation_service import innovation_service


class ProofService:
    def _parse_json_list(self, raw: str | None) -> list[Any]:
        if not raw:
            return []
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, list) else []
        except Exception:
            return []

    def _confidence_level(self, sample_size: int) -> str:
        if sample_size >= 50:
            return "high"
        if sample_size >= 15:
            return "medium"
        return "low"

    def _calc_delta(self, current: float, previous: float) -> float:
        return round(current - previous, 1)

    async def _compute_window_metrics(
        self,
        session: AsyncSession,
        org_id: int,
        period_start: datetime,
        period_end: datetime,
    ) -> dict[str, Any]:
        result_rows = (
            await session.exec(
                select(AnswerCaptureResult, AnswerCaptureRun)
                .join(AnswerCaptureRun, AnswerCaptureRun.id == AnswerCaptureResult.run_id)
                .where(
                    and_(
                        AnswerCaptureRun.org_id == org_id,
                        AnswerCaptureRun.status == "completed",
                        AnswerCaptureRun.completed_at >= period_start,
                        AnswerCaptureRun.completed_at < period_end,
                    )
                )
            )
        ).all()

        total_queries_scored = 0
        brand_mentions = 0
        citations = 0
        quality_sum = 0.0
        run_ids: set[int] = set()
        for result_row, run_row in result_rows:
            total_queries_scored += 1
            run_ids.add(run_row.id)
            if result_row.has_brand_mention:
                brand_mentions += 1
            if result_row.has_site_citation:
                citations += 1
            quality_sum += float(result_row.quality_score or 0.0)

        answer_capture_rate_pct = (
            round((brand_mentions / total_queries_scored) * 100.0, 1)
            if total_queries_scored > 0
            else 0.0
        )
        citation_rate_pct = (
            round((citations / total_queries_scored) * 100.0, 1)
            if total_queries_scored > 0
            else 0.0
        )
        average_quality_score = (
            round(quality_sum / total_queries_scored, 1)
            if total_queries_scored > 0
            else 0.0
        )

        event_rows = (
            await session.exec(
                select(AttributionEvent).where(
                    and_(
                        AttributionEvent.org_id == org_id,
                        AttributionEvent.event_timestamp >= period_start,
                        AttributionEvent.event_timestamp < period_end,
                    )
                )
            )
        ).all()

        conversions = [row for row in event_rows if row.event_name in innovation_service.CONVERSION_EVENTS]
        conversion_sessions = {row.session_key for row in conversions if row.session_key}
        ai_sessions = {row.session_key for row in event_rows if row.source_type == "ai" and row.session_key}
        ai_assisted_sessions = conversion_sessions.intersection(ai_sessions)

        ai_event_count = len([row for row in event_rows if row.source_type == "ai"])
        conversions_total = len(conversions)
        ai_assisted_conversions = len(ai_assisted_sessions)
        ai_assist_rate_pct = (
            round((ai_assisted_conversions / conversions_total) * 100.0, 1)
            if conversions_total > 0
            else 0.0
        )

        by_bot: dict[str, int] = defaultdict(int)
        for row in event_rows:
            if row.source_type == "ai" and row.source_bot_name:
                by_bot[row.source_bot_name] += 1
        top_ai_bots = sorted(
            [{"bot_name": bot, "count": count} for bot, count in by_bot.items()],
            key=lambda x: x["count"],
            reverse=True,
        )[:8]

        proof_score = round(
            min(
                100.0,
                answer_capture_rate_pct * 0.35
                + citation_rate_pct * 0.35
                + ai_assist_rate_pct * 0.30,
            ),
            1,
        )

        sample_size = total_queries_scored if total_queries_scored > 0 else conversions_total
        return {
            "period_start": period_start,
            "period_end": period_end,
            "run_count": len(run_ids),
            "total_queries_scored": total_queries_scored,
            "brand_mentions": brand_mentions,
            "citations": citations,
            "answer_capture_rate_pct": answer_capture_rate_pct,
            "citation_rate_pct": citation_rate_pct,
            "average_quality_score": average_quality_score,
            "conversions_total": conversions_total,
            "ai_assisted_conversions": ai_assisted_conversions,
            "ai_assist_rate_pct": ai_assist_rate_pct,
            "ai_event_count": ai_event_count,
            "total_event_count": len(event_rows),
            "top_ai_bots": top_ai_bots,
            "proof_score": proof_score,
            "sample_size": sample_size,
            "confidence_level": self._confidence_level(sample_size),
        }

    async def compute_overview(
        self,
        session: AsyncSession,
        org_id: int,
        period_days: int = 30,
    ) -> dict[str, Any]:
        days = min(max(int(period_days or 30), 1), 365)
        period_end = datetime.utcnow()
        period_start = period_end - timedelta(days=days)
        previous_start = period_start - timedelta(days=days)
        previous_end = period_start

        current = await self._compute_window_metrics(
            session=session,
            org_id=org_id,
            period_start=period_start,
            period_end=period_end,
        )
        previous = await self._compute_window_metrics(
            session=session,
            org_id=org_id,
            period_start=previous_start,
            period_end=previous_end,
        )

        current["deltas"] = {
            "answer_capture_rate_pct": self._calc_delta(
                current["answer_capture_rate_pct"], previous["answer_capture_rate_pct"]
            ),
            "citation_rate_pct": self._calc_delta(
                current["citation_rate_pct"], previous["citation_rate_pct"]
            ),
            "ai_assist_rate_pct": self._calc_delta(
                current["ai_assist_rate_pct"], previous["ai_assist_rate_pct"]
            ),
            "proof_score": self._calc_delta(current["proof_score"], previous["proof_score"]),
        }
        current["previous_window"] = {
            "period_start": previous_start,
            "period_end": previous_end,
            "total_queries_scored": previous["total_queries_scored"],
            "answer_capture_rate_pct": previous["answer_capture_rate_pct"],
            "citation_rate_pct": previous["citation_rate_pct"],
            "ai_assist_rate_pct": previous["ai_assist_rate_pct"],
            "proof_score": previous["proof_score"],
        }
        current["period_days"] = days
        current["measured_at"] = datetime.utcnow()
        current["evidence"] = {
            "proof_score": "measured",
            "answer_capture_rate_pct": "measured",
            "citation_rate_pct": "measured",
            "ai_assist_rate_pct": "measured",
            "average_quality_score": "measured",
            "sample_size": "measured",
            "confidence_level": "measured",
        }
        return current

    async def compute_before_after(
        self,
        session: AsyncSession,
        org_id: int,
        query_set_id: Optional[int] = None,
    ) -> dict[str, Any]:
        runs = (
            await session.exec(
                select(AnswerCaptureRun)
                .where(
                    and_(
                        AnswerCaptureRun.org_id == org_id,
                        AnswerCaptureRun.status == "completed",
                    )
                )
                .order_by(AnswerCaptureRun.completed_at.asc(), AnswerCaptureRun.id.asc())
            )
        ).all()

        grouped: dict[int, list[AnswerCaptureRun]] = defaultdict(list)
        for row in runs:
            grouped[row.query_set_id].append(row)

        selected_query_set_id = query_set_id
        if selected_query_set_id is None:
            ranked = sorted(grouped.items(), key=lambda x: len(x[1]), reverse=True)
            selected_query_set_id = ranked[0][0] if ranked else None

        if selected_query_set_id is None or len(grouped.get(selected_query_set_id, [])) < 2:
            return {
                "available": False,
                "query_set_id": selected_query_set_id,
                "message": "At least two completed runs are required for before/after comparison.",
                "items": [],
            }

        selected_runs = grouped[selected_query_set_id]
        baseline_run = selected_runs[0]
        latest_run = selected_runs[-1]

        baseline_results = (
            await session.exec(
                select(AnswerCaptureResult).where(AnswerCaptureResult.run_id == baseline_run.id)
            )
        ).all()
        latest_results = (
            await session.exec(
                select(AnswerCaptureResult).where(AnswerCaptureResult.run_id == latest_run.id)
            )
        ).all()
        items = (
            await session.exec(
                select(AnswerCaptureQueryItem)
                .where(AnswerCaptureQueryItem.query_set_id == selected_query_set_id)
                .order_by(AnswerCaptureQueryItem.priority.asc(), AnswerCaptureQueryItem.id.asc())
            )
        ).all()

        baseline_by_query_id = {row.query_item_id: row for row in baseline_results}
        latest_by_query_id = {row.query_item_id: row for row in latest_results}
        item_by_id = {row.id: row for row in items if row.id is not None}

        compared_items: list[dict[str, Any]] = []
        brand_improved_count = 0
        citation_improved_count = 0
        quality_delta_sum = 0.0
        quality_delta_count = 0

        query_ids = sorted(set(baseline_by_query_id.keys()) | set(latest_by_query_id.keys()))
        for query_item_id in query_ids:
            baseline = baseline_by_query_id.get(query_item_id)
            latest = latest_by_query_id.get(query_item_id)
            meta = item_by_id.get(query_item_id)

            baseline_quality = float(baseline.quality_score) if baseline else 0.0
            latest_quality = float(latest.quality_score) if latest else 0.0
            quality_delta = round(latest_quality - baseline_quality, 1)

            if baseline and latest:
                quality_delta_sum += quality_delta
                quality_delta_count += 1
                if (not baseline.has_brand_mention) and latest.has_brand_mention:
                    brand_improved_count += 1
                if (not baseline.has_site_citation) and latest.has_site_citation:
                    citation_improved_count += 1

            compared_items.append(
                {
                    "query_item_id": query_item_id,
                    "prompt_text": meta.prompt_text if meta else f"Query #{query_item_id}",
                    "baseline": {
                        "has_brand_mention": bool(baseline.has_brand_mention) if baseline else False,
                        "has_site_citation": bool(baseline.has_site_citation) if baseline else False,
                        "quality_score": baseline_quality,
                        "answer_text": (baseline.answer_text or "") if baseline else "",
                        "cited_urls": self._parse_json_list(baseline.cited_urls_json) if baseline else [],
                    },
                    "latest": {
                        "has_brand_mention": bool(latest.has_brand_mention) if latest else False,
                        "has_site_citation": bool(latest.has_site_citation) if latest else False,
                        "quality_score": latest_quality,
                        "answer_text": (latest.answer_text or "") if latest else "",
                        "cited_urls": self._parse_json_list(latest.cited_urls_json) if latest else [],
                    },
                    "delta": {
                        "quality_score": quality_delta,
                    },
                }
            )

        return {
            "available": True,
            "query_set_id": selected_query_set_id,
            "baseline_run": {
                "id": baseline_run.id,
                "completed_at": baseline_run.completed_at,
            },
            "latest_run": {
                "id": latest_run.id,
                "completed_at": latest_run.completed_at,
            },
            "summary": {
                "query_item_count": len(compared_items),
                "brand_improved_count": brand_improved_count,
                "citation_improved_count": citation_improved_count,
                "average_quality_delta": round(
                    quality_delta_sum / quality_delta_count, 1
                )
                if quality_delta_count > 0
                else 0.0,
            },
            "items": compared_items,
        }

    async def save_snapshot(
        self,
        session: AsyncSession,
        org_id: int,
        user_id: int,
        overview: dict[str, Any],
    ) -> ProofSnapshot:
        row = ProofSnapshot(
            org_id=org_id,
            created_by_user_id=user_id,
            period_start=overview["period_start"],
            period_end=overview["period_end"],
            total_queries_scored=int(overview.get("total_queries_scored", 0)),
            answer_capture_rate_pct=float(overview.get("answer_capture_rate_pct", 0.0)),
            citation_rate_pct=float(overview.get("citation_rate_pct", 0.0)),
            average_quality_score=float(overview.get("average_quality_score", 0.0)),
            ai_assist_rate_pct=float(overview.get("ai_assist_rate_pct", 0.0)),
            conversions_total=int(overview.get("conversions_total", 0)),
            ai_assisted_conversions=int(overview.get("ai_assisted_conversions", 0)),
            confidence_level=str(overview.get("confidence_level", "low")),
            metadata_json=json.dumps(
                {
                    "proof_score": overview.get("proof_score", 0.0),
                    "sample_size": overview.get("sample_size", 0),
                    "deltas": overview.get("deltas", {}),
                },
                ensure_ascii=True,
            ),
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return row

    async def list_snapshots(
        self,
        session: AsyncSession,
        org_id: int,
        limit: int = 30,
    ) -> list[ProofSnapshot]:
        bounded = min(max(int(limit or 30), 1), 200)
        rows = (
            await session.exec(
                select(ProofSnapshot)
                .where(ProofSnapshot.org_id == org_id)
                .order_by(ProofSnapshot.created_at.desc())
                .limit(bounded)
            )
        ).all()
        return rows


proof_service = ProofService()
