import asyncio
import uuid
from datetime import datetime

from fastapi.testclient import TestClient
from sqlmodel import select

from app.db.engine import get_session
from app.main import app
from app.models.analytics import BotVisit, BridgeEvent
from app.models.approval import ApprovalRequest
from app.models.billing import Subscription
from app.models.innovation import (
    AnswerCaptureQueryItem,
    AnswerCaptureQuerySet,
    AnswerCaptureResult,
    AnswerCaptureRun,
    AttributionEvent,
    OnboardingProgress,
    ProofSnapshot,
)
from app.models.organization import Membership, Organization
from app.models.site import Site
from app.models.user import User


PASSWORD = "Passw0rd!@#"


async def _get_user_by_email(email: str) -> User | None:
    async for session in get_session():
        return (await session.exec(select(User).where(User.email == email))).first()


async def _get_org_id_by_email(email: str) -> int | None:
    async for session in get_session():
        user = (await session.exec(select(User).where(User.email == email))).first()
        if not user:
            return None
        membership = (await session.exec(select(Membership).where(Membership.user_id == user.id))).first()
        return membership.org_id if membership else None


async def _seed_site_and_signals(org_id: int, owner_id: int, url: str) -> Site:
    async for session in get_session():
        site = Site(
            org_id=org_id,
            owner_id=owner_id,
            url=url,
            status="completed",
            ai_score=86,
            schema_type="WebSite",
            seo_description="Daily report test seed",
            updated_at=datetime.utcnow(),
        )
        session.add(site)
        await session.commit()
        await session.refresh(site)

        session.add(
            BotVisit(
                site_id=site.id,
                bot_name="GPTBot",
                user_agent="pytest",
                served_asset_type="script",
            )
        )
        session.add(
            BotVisit(
                site_id=site.id,
                bot_name="Human/Browser",
                user_agent="pytest-browser",
                served_asset_type="script",
            )
        )
        session.add(
            BridgeEvent(
                site_id=site.id,
                session_id="pytest-session",
                event_type="pageview",
                page_url="/",
                user_agent="pytest",
            )
        )
        await session.commit()
        return site


async def _cleanup(prefix: str) -> None:
    async for session in get_session():
        users = (
            await session.exec(select(User).where(User.email.like(f"{prefix}%@example.com")))
        ).all()
        user_ids = [row.id for row in users if row.id is not None]

        orgs = (
            await session.exec(
                select(Organization).where(Organization.billing_email.like(f"{prefix}%@example.com"))
            )
        ).all()
        org_ids = [row.id for row in orgs if row.id is not None]

        if org_ids:
            proof_snapshots = (
                await session.exec(select(ProofSnapshot).where(ProofSnapshot.org_id.in_(org_ids)))
            ).all()
            for row in proof_snapshots:
                await session.delete(row)

            onboarding_steps = (
                await session.exec(select(OnboardingProgress).where(OnboardingProgress.org_id.in_(org_ids)))
            ).all()
            for row in onboarding_steps:
                await session.delete(row)

            attribution_events = (
                await session.exec(select(AttributionEvent).where(AttributionEvent.org_id.in_(org_ids)))
            ).all()
            for row in attribution_events:
                await session.delete(row)

            query_sets = (
                await session.exec(select(AnswerCaptureQuerySet).where(AnswerCaptureQuerySet.org_id.in_(org_ids)))
            ).all()
            query_set_ids = [row.id for row in query_sets if row.id is not None]

            runs = (
                await session.exec(select(AnswerCaptureRun).where(AnswerCaptureRun.org_id.in_(org_ids)))
            ).all()
            run_ids = [row.id for row in runs if row.id is not None]

            if run_ids:
                run_results = (
                    await session.exec(select(AnswerCaptureResult).where(AnswerCaptureResult.run_id.in_(run_ids)))
                ).all()
                for row in run_results:
                    await session.delete(row)

            for row in runs:
                await session.delete(row)

            if query_set_ids:
                query_items = (
                    await session.exec(
                        select(AnswerCaptureQueryItem).where(AnswerCaptureQueryItem.query_set_id.in_(query_set_ids))
                    )
                ).all()
                for row in query_items:
                    await session.delete(row)

            for row in query_sets:
                await session.delete(row)

            approval_rows = (
                await session.exec(select(ApprovalRequest).where(ApprovalRequest.org_id.in_(org_ids)))
            ).all()
            for row in approval_rows:
                await session.delete(row)

            sites = (await session.exec(select(Site).where(Site.org_id.in_(org_ids)))).all()
            site_ids = [row.id for row in sites if row.id is not None]

            if site_ids:
                bot_visits = (
                    await session.exec(select(BotVisit).where(BotVisit.site_id.in_(site_ids)))
                ).all()
                for row in bot_visits:
                    await session.delete(row)

                bridge_events = (
                    await session.exec(select(BridgeEvent).where(BridgeEvent.site_id.in_(site_ids)))
                ).all()
                for row in bridge_events:
                    await session.delete(row)

            for row in sites:
                await session.delete(row)

            subscriptions = (
                await session.exec(select(Subscription).where(Subscription.org_id.in_(org_ids)))
            ).all()
            for row in subscriptions:
                await session.delete(row)

            memberships_by_org = (
                await session.exec(select(Membership).where(Membership.org_id.in_(org_ids)))
            ).all()
            for row in memberships_by_org:
                await session.delete(row)

            for org in orgs:
                await session.delete(org)

        if user_ids:
            memberships_by_user = (
                await session.exec(select(Membership).where(Membership.user_id.in_(user_ids)))
            ).all()
            for row in memberships_by_user:
                await session.delete(row)

        for row in users:
            await session.delete(row)

        await session.commit()
        break


def test_manual_daily_reports_and_global_ui_language_flow():
    prefix = f"pytest_manual_daily_{uuid.uuid4().hex[:8]}_"
    email = f"{prefix}owner@example.com"

    try:
        with TestClient(app) as client:
            register = client.post(
                "/auth/register",
                data={"email": email, "password": PASSWORD, "full_name": "Manual Owner"},
                follow_redirects=False,
            )
            assert register.status_code == 303

            login = client.post(
                "/auth/login",
                data={"username": email, "password": PASSWORD},
                follow_redirects=False,
            )
            assert login.status_code == 303

            org_id = asyncio.run(_get_org_id_by_email(email))
            user = asyncio.run(_get_user_by_email(email))
            assert org_id is not None
            assert user is not None and user.id is not None

            asyncio.run(_seed_site_and_signals(org_id, user.id, f"https://{prefix}site.example"))

            dashboard = client.get(f"/dashboard?org_id={org_id}")
            assert dashboard.status_code == 200
            assert "Journey Flow" in dashboard.text
            assert "All Sites Language" not in dashboard.text
            assert 'name="language"' in dashboard.text
            assert "Save Workspace Language" not in dashboard.text
            assert 'onchange="this.form.submit()"' in dashboard.text
            assert "Japanese (日本語)" in dashboard.text
            assert "Chinese Simplified (简体中文)" in dashboard.text
            assert "Hindi (हिन्दी)" in dashboard.text
            assert "predicted" in dashboard.text.lower()
            assert "confidence" in dashboard.text.lower()

            set_language = client.post(
                "/users/ui-language",
                data={"language": "ko", "next_url": f"/dashboard?org_id={org_id}"},
                follow_redirects=False,
            )
            assert set_language.status_code == 303
            assert set_language.headers.get("location") == f"/dashboard?org_id={org_id}"
            assert "ghostlink_ui_language=ko" in (set_language.headers.get("set-cookie") or "")

            updated_user = asyncio.run(_get_user_by_email(email))
            assert updated_user is not None
            assert updated_user.preferred_ui_language == "ko"

            dashboard_after = client.get(f"/dashboard?org_id={org_id}")
            assert dashboard_after.status_code == 200
            assert '<html lang="ko"' in dashboard_after.text
            assert "고객 운영 대시보드" in dashboard_after.text
            assert "Customer Operations Dashboard" not in dashboard_after.text
            assert "홈" in dashboard_after.text

            landing_after = client.get("/")
            assert landing_after.status_code == 200
            assert '<html lang="ko"' in landing_after.text
            assert "당신의 웹사이트를" in landing_after.text
            assert "단순하고 투명한 요금제" in landing_after.text
            assert "Make Your Website" not in landing_after.text
            assert "Simple, Transparent Pricing" not in landing_after.text

            set_language_ja = client.post(
                "/users/ui-language",
                data={"language": "ja", "next_url": "/"},
                follow_redirects=False,
            )
            assert set_language_ja.status_code == 303
            assert set_language_ja.headers.get("location") == "/"
            assert "ghostlink_ui_language=ja" in (set_language_ja.headers.get("set-cookie") or "")

            landing_ja = client.get("/")
            assert landing_ja.status_code == 200
            assert '<html lang="ja"' in landing_ja.text
            assert "ウェブサイトを" in landing_ja.text
            assert "シンプルで明確な料金" in landing_ja.text
            assert "Make Your Website" not in landing_ja.text

            manual_page = client.get(f"/manual?org_id={org_id}")
            assert manual_page.status_code == 200
            assert "고객 여정 매뉴얼" in manual_page.text
            assert "단계 7" in manual_page.text
            assert "index.html" in manual_page.text
            assert "/manual/execution-board" in manual_page.text

            execution_board = client.get(f"/manual/execution-board?org_id={org_id}")
            assert execution_board.status_code == 200
            assert "고스트링크 정밀 개선 보고서" in execution_board.text
            assert "실행 백로그" in execution_board.text

            daily_page = client.get(f"/reports/daily?org_id={org_id}")
            assert daily_page.status_code == 200
            assert "일일 리포트" in daily_page.text
            assert "PDF 다운로드" in daily_page.text
            assert "신뢰도" in daily_page.text
            assert "고객 신뢰 내러티브" in daily_page.text

            daily_json = client.get(f"/api/v1/reports/daily?org_id={org_id}")
            assert daily_json.status_code == 200
            payload = daily_json.json()
            assert payload["org_id"] == org_id
            assert payload["site_count"] >= 1
            assert payload["ai_crawler_visits"] >= 1
            assert payload["human_visits"] >= 1
            assert payload["bridge_event_count"] >= 1
            assert payload["evidence"]["avg_visibility_score"] == "predicted"
            assert payload["evidence"]["proof"]["answer_capture_rate_pct"] == "measured"
            assert payload["proof"]["confidence_level"] in {"low", "medium", "high"}
            assert "optimization_impact" in payload
            assert "totals" in payload["optimization_impact"]

            proof_overview = client.get(f"/api/v1/proof/overview?org_id={org_id}")
            assert proof_overview.status_code == 200
            overview_payload = proof_overview.json()
            assert overview_payload["evidence"]["proof_score"] == "measured"

            daily_pdf = client.get(f"/api/v1/reports/daily.pdf?org_id={org_id}")
            assert daily_pdf.status_code == 200
            assert daily_pdf.headers.get("content-type", "").startswith("application/pdf")
            assert "attachment; filename=\"ghostlink-daily-report-" in (
                daily_pdf.headers.get("content-disposition") or ""
            )
            assert daily_pdf.content.startswith(b"%PDF")
    finally:
        asyncio.run(_cleanup(prefix))
