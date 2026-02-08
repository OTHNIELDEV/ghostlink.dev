import asyncio
import uuid
from datetime import datetime

from fastapi.testclient import TestClient
from sqlmodel import select

from app.db.engine import get_session
from app.main import app
from app.models.analytics import BotVisit, BridgeEvent
from app.models.billing import Subscription
from app.models.innovation import (
    AnswerCaptureQueryItem,
    AnswerCaptureQuerySet,
    AnswerCaptureResult,
    AnswerCaptureRun,
    AttributionEvent,
    AttributionSnapshot,
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


async def _create_site(org_id: int, owner_id: int, url: str) -> Site:
    async for session in get_session():
        site = Site(
            org_id=org_id,
            owner_id=owner_id,
            url=url,
            status="completed",
            ai_score=81,
            seo_description="Proof center baseline",
            schema_type="WebSite",
            updated_at=datetime.utcnow(),
        )
        session.add(site)
        await session.commit()
        await session.refresh(site)
        return site


async def _seed_installation_signals(site_id: int) -> None:
    async for session in get_session():
        session.add(
            BotVisit(
                site_id=site_id,
                bot_name="Human/Browser",
                user_agent="pytest",
                served_asset_type="script",
            )
        )
        session.add(
            BridgeEvent(
                site_id=site_id,
                session_id="pytest-session",
                event_type="pageview",
                page_url="/",
                user_agent="pytest",
            )
        )
        await session.commit()
        break


async def _cleanup(prefix: str) -> None:
    async for session in get_session():
        users = (
            await session.exec(select(User).where(User.email.like(f"{prefix}%@example.com")))
        ).all()
        user_ids = [u.id for u in users if u.id is not None]

        orgs = (
            await session.exec(
                select(Organization).where(Organization.billing_email.like(f"{prefix}%@example.com"))
            )
        ).all()
        org_ids = [o.id for o in orgs if o.id is not None]

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

            attribution_snapshots = (
                await session.exec(select(AttributionSnapshot).where(AttributionSnapshot.org_id.in_(org_ids)))
            ).all()
            for row in attribution_snapshots:
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

            sites = (
                await session.exec(select(Site).where(Site.org_id.in_(org_ids)))
            ).all()
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

        for user in users:
            await session.delete(user)

        await session.commit()
        break


def test_onboarding_and_proof_center_end_to_end():
    prefix = f"pytest_proof_{uuid.uuid4().hex[:8]}_"
    email = f"{prefix}owner@example.com"

    try:
        with TestClient(app) as client:
            register = client.post(
                "/auth/register",
                data={"email": email, "password": PASSWORD, "full_name": "Proof Owner"},
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

            site = asyncio.run(_create_site(org_id, user.id, f"https://{prefix}site.example"))
            asyncio.run(_seed_installation_signals(site.id))

            query_set_resp = client.post(
                f"/api/v1/answer-capture/query-sets?org_id={org_id}",
                json={"name": "Proof Queries", "description": "core", "default_brand_terms": ["GhostLink"]},
            )
            assert query_set_resp.status_code == 200
            query_set_id = query_set_resp.json()["id"]

            query_item_resp = client.post(
                f"/api/v1/answer-capture/query-sets/{query_set_id}/queries?org_id={org_id}",
                json={"prompt_text": "What is GhostLink?", "expected_brand_terms": ["GhostLink"], "priority": 1},
            )
            assert query_item_resp.status_code == 200
            query_item_id = query_item_resp.json()["id"]

            run1 = client.post(
                f"/api/v1/answer-capture/runs?org_id={org_id}",
                json={
                    "query_set_id": query_set_id,
                    "responses": [
                        {
                            "query_item_id": query_item_id,
                            "answer_text": "Generic SEO tool.",
                            "cited_urls": ["https://external.example/a"],
                        }
                    ],
                },
            )
            assert run1.status_code == 200

            run2 = client.post(
                f"/api/v1/answer-capture/runs?org_id={org_id}",
                json={
                    "query_set_id": query_set_id,
                    "responses": [
                        {
                            "query_item_id": query_item_id,
                            "answer_text": "GhostLink is an AI visibility and proof platform.",
                            "cited_urls": [site.url + "/pricing"],
                        }
                    ],
                },
            )
            assert run2.status_code == 200

            ai_event = client.post(
                f"/api/v1/attribution/events?org_id={org_id}",
                json={
                    "session_key": "proof-ai-1",
                    "event_name": "trial_started",
                    "source_type": "ai",
                    "source_bot_name": "GPTBot",
                },
            )
            assert ai_event.status_code == 200
            human_event = client.post(
                f"/api/v1/attribution/events?org_id={org_id}",
                json={
                    "session_key": "proof-human-1",
                    "event_name": "trial_started",
                    "source_type": "human",
                },
            )
            assert human_event.status_code == 200

            onboarding = client.get(f"/api/v1/onboarding/status?org_id={org_id}")
            assert onboarding.status_code == 200
            onboarding_payload = onboarding.json()
            assert onboarding_payload["completed_count"] >= 4

            proof_overview = client.get(f"/api/v1/proof/overview?org_id={org_id}&period_days=30")
            assert proof_overview.status_code == 200
            overview_payload = proof_overview.json()
            assert overview_payload["total_queries_scored"] >= 2
            assert overview_payload["answer_capture_rate_pct"] >= 50.0
            assert overview_payload["citation_rate_pct"] >= 50.0
            assert overview_payload["ai_assist_rate_pct"] >= 50.0

            before_after = client.get(
                f"/api/v1/proof/before-after?org_id={org_id}&query_set_id={query_set_id}"
            )
            assert before_after.status_code == 200
            before_after_payload = before_after.json()
            assert before_after_payload["available"] is True
            assert before_after_payload["summary"]["query_item_count"] >= 1

            proof_page = client.get(f"/proof?org_id={org_id}&query_set_id={query_set_id}")
            assert proof_page.status_code == 200
            assert "Proof Center" in proof_page.text
            assert "Before / After Evidence" in proof_page.text

            integration_page = client.get(f"/docs/integration-guide?org_id={org_id}&site_id={site.id}")
            assert integration_page.status_code == 200
            assert "index.html" in integration_page.text
            assert "GhostLink Integration Guide" in integration_page.text
    finally:
        asyncio.run(_cleanup(prefix))
