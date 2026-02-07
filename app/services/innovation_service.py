import json
from datetime import datetime, timedelta
from typing import Any, Optional
from urllib.parse import urlparse

from sqlmodel import and_, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.innovation import (
    AnswerCaptureQueryItem,
    AnswerCaptureQuerySet,
    AnswerCaptureResult,
    AnswerCaptureRun,
    AttributionEvent,
    AttributionSnapshot,
)
from app.models.site import Site


class InnovationService:
    CONVERSION_EVENTS = {
        "conversion",
        "purchase_completed",
        "signup_completed",
        "trial_started",
        "demo_booked",
    }

    def parse_json_list(self, raw: str | None) -> list[Any]:
        if not raw:
            return []
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, list) else []
        except Exception:
            return []

    def parse_json_dict(self, raw: str | None) -> dict[str, Any]:
        if not raw:
            return {}
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}

    def _normalize_terms(self, terms: Optional[list[str]]) -> list[str]:
        normalized = []
        for term in terms or []:
            candidate = str(term).strip()
            if candidate:
                normalized.append(candidate)
        seen = set()
        unique = []
        for term in normalized:
            lowered = term.lower()
            if lowered not in seen:
                seen.add(lowered)
                unique.append(term)
        return unique

    def _extract_host(self, raw_url: str) -> str | None:
        try:
            parsed = urlparse(raw_url or "")
            host = (parsed.netloc or "").lower().strip()
            if host.startswith("www."):
                host = host[4:]
            return host or None
        except Exception:
            return None

    def _match_org_host(self, cited_url: str, org_hosts: set[str]) -> bool:
        host = self._extract_host(cited_url)
        if not host:
            return False
        return host in org_hosts

    def _score_quality(self, has_brand_mention: bool, has_site_citation: bool, answer_text: str) -> float:
        score = 0.0
        if has_brand_mention:
            score += 60.0
        if has_site_citation:
            score += 35.0
        if len((answer_text or "").strip()) >= 120:
            score += 5.0
        return min(score, 100.0)

    async def list_query_sets(self, session: AsyncSession, org_id: int) -> list[AnswerCaptureQuerySet]:
        rows = await session.exec(
            select(AnswerCaptureQuerySet)
            .where(AnswerCaptureQuerySet.org_id == org_id)
            .order_by(AnswerCaptureQuerySet.created_at.desc())
        )
        return rows.all()

    async def create_query_set(
        self,
        session: AsyncSession,
        org_id: int,
        user_id: int,
        name: str,
        description: Optional[str],
        default_brand_terms: Optional[list[str]],
    ) -> AnswerCaptureQuerySet:
        row = AnswerCaptureQuerySet(
            org_id=org_id,
            created_by_user_id=user_id,
            name=name.strip(),
            description=(description or "").strip() or None,
            default_brand_terms_json=json.dumps(
                self._normalize_terms(default_brand_terms),
                ensure_ascii=True,
            ),
            is_active=True,
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return row

    async def get_query_set(self, session: AsyncSession, query_set_id: int, org_id: int) -> Optional[AnswerCaptureQuerySet]:
        row = await session.exec(
            select(AnswerCaptureQuerySet).where(
                and_(
                    AnswerCaptureQuerySet.id == query_set_id,
                    AnswerCaptureQuerySet.org_id == org_id,
                )
            )
        )
        return row.first()

    async def list_query_items(
        self,
        session: AsyncSession,
        query_set_id: int,
    ) -> list[AnswerCaptureQueryItem]:
        rows = await session.exec(
            select(AnswerCaptureQueryItem)
            .where(AnswerCaptureQueryItem.query_set_id == query_set_id)
            .order_by(AnswerCaptureQueryItem.priority.asc(), AnswerCaptureQueryItem.id.asc())
        )
        return rows.all()

    async def create_query_item(
        self,
        session: AsyncSession,
        query_set: AnswerCaptureQuerySet,
        prompt_text: str,
        expected_brand_terms: Optional[list[str]],
        priority: int = 100,
    ) -> AnswerCaptureQueryItem:
        prompt = (prompt_text or "").strip()
        if not prompt:
            raise ValueError("prompt_text is required")

        terms = expected_brand_terms
        if terms is None:
            terms = [str(x) for x in self.parse_json_list(query_set.default_brand_terms_json)]

        row = AnswerCaptureQueryItem(
            query_set_id=query_set.id,
            prompt_text=prompt,
            expected_brand_terms_json=json.dumps(self._normalize_terms(terms), ensure_ascii=True),
            priority=max(1, int(priority or 100)),
            is_active=True,
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return row

    async def create_run_with_results(
        self,
        session: AsyncSession,
        org_id: int,
        query_set: AnswerCaptureQuerySet,
        user_id: int,
        provider: str,
        model: str,
        responses: list[dict[str, Any]],
    ) -> tuple[AnswerCaptureRun, list[AnswerCaptureResult], dict[str, Any]]:
        run = AnswerCaptureRun(
            org_id=org_id,
            query_set_id=query_set.id,
            created_by_user_id=user_id,
            status="processing",
            provider=(provider or "openai").strip().lower(),
            model=(model or "gpt-4o-mini").strip(),
            started_at=datetime.utcnow(),
        )
        session.add(run)
        await session.commit()
        await session.refresh(run)

        items = await self.list_query_items(session, query_set.id)
        item_by_id = {item.id: item for item in items if item.id is not None}

        org_sites = (
            await session.exec(select(Site).where(Site.org_id == org_id))
        ).all()
        org_hosts = {
            host
            for host in [self._extract_host(site.url) for site in org_sites]
            if host
        }

        created_results: list[AnswerCaptureResult] = []
        brand_mentions = 0
        citations = 0
        score_sum = 0.0

        for payload in responses:
            query_item_id = int(payload.get("query_item_id") or 0)
            item = item_by_id.get(query_item_id)
            if not item:
                continue

            answer_text = str(payload.get("answer_text") or "").strip()
            cited_urls_raw = payload.get("cited_urls")
            cited_urls = [
                str(url).strip()
                for url in (cited_urls_raw or [])
                if str(url).strip()
            ]
            expected_terms = [
                str(x).lower()
                for x in self.parse_json_list(item.expected_brand_terms_json)
                if str(x).strip()
            ]
            answer_lower = answer_text.lower()
            has_brand_mention = any(term in answer_lower for term in expected_terms) if expected_terms else False
            has_site_citation = any(self._match_org_host(url, org_hosts) for url in cited_urls)
            quality_score = self._score_quality(has_brand_mention, has_site_citation, answer_text)

            row = AnswerCaptureResult(
                run_id=run.id,
                query_item_id=query_item_id,
                answer_text=answer_text,
                cited_urls_json=json.dumps(cited_urls, ensure_ascii=True),
                has_brand_mention=has_brand_mention,
                has_site_citation=has_site_citation,
                quality_score=quality_score,
            )
            session.add(row)
            created_results.append(row)

            if has_brand_mention:
                brand_mentions += 1
            if has_site_citation:
                citations += 1
            score_sum += quality_score

        await session.commit()
        for row in created_results:
            await session.refresh(row)

        total = len(created_results)
        summary = {
            "total_queries_scored": total,
            "brand_mention_rate_pct": round((brand_mentions / total) * 100.0, 1) if total > 0 else 0.0,
            "citation_rate_pct": round((citations / total) * 100.0, 1) if total > 0 else 0.0,
            "average_quality_score": round(score_sum / total, 1) if total > 0 else 0.0,
        }

        run.status = "completed"
        run.completed_at = datetime.utcnow()
        run.summary_json = json.dumps(summary, ensure_ascii=True)
        session.add(run)
        await session.commit()
        await session.refresh(run)
        return run, created_results, summary

    async def list_runs(
        self,
        session: AsyncSession,
        org_id: int,
        query_set_id: Optional[int] = None,
        limit: int = 50,
    ) -> list[AnswerCaptureRun]:
        bounded_limit = min(max(limit, 1), 200)
        query = select(AnswerCaptureRun).where(AnswerCaptureRun.org_id == org_id)
        if query_set_id:
            query = query.where(AnswerCaptureRun.query_set_id == query_set_id)
        query = query.order_by(AnswerCaptureRun.created_at.desc()).limit(bounded_limit)
        rows = await session.exec(query)
        return rows.all()

    async def get_run(
        self,
        session: AsyncSession,
        org_id: int,
        run_id: int,
    ) -> Optional[AnswerCaptureRun]:
        row = await session.exec(
            select(AnswerCaptureRun).where(
                and_(
                    AnswerCaptureRun.id == run_id,
                    AnswerCaptureRun.org_id == org_id,
                )
            )
        )
        return row.first()

    async def list_results_for_run(
        self,
        session: AsyncSession,
        run_id: int,
    ) -> list[AnswerCaptureResult]:
        rows = await session.exec(
            select(AnswerCaptureResult)
            .where(AnswerCaptureResult.run_id == run_id)
            .order_by(AnswerCaptureResult.id.asc())
        )
        return rows.all()

    async def record_attribution_event(
        self,
        session: AsyncSession,
        org_id: int,
        user_id: int,
        payload: dict[str, Any],
    ) -> AttributionEvent:
        event = AttributionEvent(
            org_id=org_id,
            user_id=user_id,
            site_id=payload.get("site_id"),
            session_key=str(payload.get("session_key") or "").strip(),
            source_type=str(payload.get("source_type") or "unknown").strip().lower(),
            source_bot_name=(str(payload.get("source_bot_name") or "").strip() or None),
            referrer=(str(payload.get("referrer") or "").strip() or None),
            utm_source=(str(payload.get("utm_source") or "").strip() or None),
            utm_medium=(str(payload.get("utm_medium") or "").strip() or None),
            utm_campaign=(str(payload.get("utm_campaign") or "").strip() or None),
            event_name=str(payload.get("event_name") or "").strip().lower(),
            event_value=float(payload.get("event_value") or 0.0),
            event_timestamp=payload.get("event_timestamp") or datetime.utcnow(),
            metadata_json=json.dumps(payload.get("metadata") or {}, ensure_ascii=True),
        )
        if not event.session_key:
            raise ValueError("session_key is required")
        if not event.event_name:
            raise ValueError("event_name is required")

        session.add(event)
        await session.commit()
        await session.refresh(event)
        return event

    async def compute_attribution_snapshot(
        self,
        session: AsyncSession,
        org_id: int,
        period_days: int = 30,
    ) -> dict[str, Any]:
        days = min(max(period_days, 1), 365)
        period_end = datetime.utcnow()
        period_start = period_end - timedelta(days=days)

        rows = (
            await session.exec(
                select(AttributionEvent).where(
                    and_(
                        AttributionEvent.org_id == org_id,
                        AttributionEvent.event_timestamp >= period_start,
                        AttributionEvent.event_timestamp <= period_end,
                    )
                )
            )
        ).all()

        conversions = [row for row in rows if row.event_name in self.CONVERSION_EVENTS]
        conversion_sessions = {row.session_key for row in conversions if row.session_key}
        ai_sessions = {row.session_key for row in rows if row.source_type == "ai" and row.session_key}
        ai_assisted = conversion_sessions.intersection(ai_sessions)

        by_bot: dict[str, int] = {}
        for row in rows:
            if row.source_type == "ai" and row.source_bot_name:
                by_bot[row.source_bot_name] = by_bot.get(row.source_bot_name, 0) + 1

        conversions_total = len(conversions)
        ai_assisted_total = len(ai_assisted)
        ai_assist_rate = round((ai_assisted_total / conversions_total) * 100.0, 1) if conversions_total > 0 else 0.0

        return {
            "org_id": org_id,
            "period_days": days,
            "period_start": period_start,
            "period_end": period_end,
            "conversions_total": conversions_total,
            "ai_assisted_conversions": ai_assisted_total,
            "ai_assist_rate_pct": ai_assist_rate,
            "ai_event_count": len([row for row in rows if row.source_type == "ai"]),
            "total_event_count": len(rows),
            "top_ai_bots": sorted(
                [{"bot_name": k, "count": v} for k, v in by_bot.items()],
                key=lambda x: x["count"],
                reverse=True,
            )[:10],
        }

    async def save_attribution_snapshot(
        self,
        session: AsyncSession,
        org_id: int,
        snapshot: dict[str, Any],
    ) -> AttributionSnapshot:
        row = AttributionSnapshot(
            org_id=org_id,
            period_start=snapshot["period_start"],
            period_end=snapshot["period_end"],
            conversions_total=int(snapshot["conversions_total"]),
            ai_assisted_conversions=int(snapshot["ai_assisted_conversions"]),
            ai_assist_rate_pct=float(snapshot["ai_assist_rate_pct"]),
            metadata_json=json.dumps(
                {
                    "period_days": snapshot.get("period_days"),
                    "ai_event_count": snapshot.get("ai_event_count"),
                    "total_event_count": snapshot.get("total_event_count"),
                    "top_ai_bots": snapshot.get("top_ai_bots", []),
                },
                ensure_ascii=True,
            ),
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return row

    async def list_attribution_snapshots(
        self,
        session: AsyncSession,
        org_id: int,
        limit: int = 30,
    ) -> list[AttributionSnapshot]:
        bounded_limit = min(max(limit, 1), 200)
        rows = await session.exec(
            select(AttributionSnapshot)
            .where(AttributionSnapshot.org_id == org_id)
            .order_by(AttributionSnapshot.created_at.desc())
            .limit(bounded_limit)
        )
        return rows.all()


innovation_service = InnovationService()
