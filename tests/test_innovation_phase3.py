import asyncio
import uuid

from fastapi.testclient import TestClient
from sqlmodel import select

from app.db.engine import get_session
from app.main import app
from app.models.billing import Subscription
from app.models.innovation import (
    AnswerCaptureQueryItem,
    AnswerCaptureQuerySet,
    AnswerCaptureResult,
    AnswerCaptureRun,
    AttributionEvent,
    AttributionSnapshot,
)
from app.models.organization import Membership, Organization
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


async def _add_member_to_org(org_id: int, user_id: int, role: str = "member") -> None:
    async for session in get_session():
        existing = (
            await session.exec(
                select(Membership).where(
                    Membership.org_id == org_id,
                    Membership.user_id == user_id,
                )
            )
        ).first()
        if existing:
            existing.role = role
            session.add(existing)
        else:
            session.add(Membership(org_id=org_id, user_id=user_id, role=role))
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
            snapshots = (
                await session.exec(select(AttributionSnapshot).where(AttributionSnapshot.org_id.in_(org_ids)))
            ).all()
            for row in snapshots:
                await session.delete(row)

            events = (
                await session.exec(select(AttributionEvent).where(AttributionEvent.org_id.in_(org_ids)))
            ).all()
            for row in events:
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
                results = (
                    await session.exec(select(AnswerCaptureResult).where(AnswerCaptureResult.run_id.in_(run_ids)))
                ).all()
                for row in results:
                    await session.delete(row)

            for row in runs:
                await session.delete(row)

            if query_set_ids:
                query_items = (
                    await session.exec(select(AnswerCaptureQueryItem).where(AnswerCaptureQueryItem.query_set_id.in_(query_set_ids)))
                ).all()
                for row in query_items:
                    await session.delete(row)

            for row in query_sets:
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


def test_innovation_top2_core_flow():
    prefix = f"pytest_innov_{uuid.uuid4().hex[:8]}_"
    owner_email = f"{prefix}owner@example.com"
    try:
        with TestClient(app) as client:
            register = client.post(
                "/auth/register",
                data={"email": owner_email, "password": PASSWORD, "full_name": "Innovation Owner"},
                follow_redirects=False,
            )
            assert register.status_code == 303

            login = client.post(
                "/auth/login",
                data={"username": owner_email, "password": PASSWORD},
                follow_redirects=False,
            )
            assert login.status_code == 303

            org_id = asyncio.run(_get_org_id_by_email(owner_email))
            assert org_id is not None

            query_set = client.post(
                f"/api/v1/answer-capture/query-sets?org_id={org_id}",
                json={
                    "name": "Core Questions",
                    "description": "Weekly score",
                    "default_brand_terms": ["GhostLink"],
                },
            )
            assert query_set.status_code == 200
            query_set_id = query_set.json()["id"]

            query_item = client.post(
                f"/api/v1/answer-capture/query-sets/{query_set_id}/queries?org_id={org_id}",
                json={
                    "prompt_text": "What is GhostLink?",
                    "expected_brand_terms": ["GhostLink", "AI SEO"],
                    "priority": 10,
                },
            )
            assert query_item.status_code == 200
            query_item_id = query_item.json()["id"]

            run = client.post(
                f"/api/v1/answer-capture/runs?org_id={org_id}",
                json={
                    "query_set_id": query_set_id,
                    "provider": "openai",
                    "model": "gpt-4o-mini",
                    "responses": [
                        {
                            "query_item_id": query_item_id,
                            "answer_text": "GhostLink is an AI SEO platform.",
                            "cited_urls": ["https://example.com/no-match"],
                        }
                    ],
                },
            )
            assert run.status_code == 200
            assert run.json()["summary"]["total_queries_scored"] == 1

            event = client.post(
                f"/api/v1/attribution/events?org_id={org_id}",
                json={
                    "session_key": "sess-innov-1",
                    "event_name": "trial_started",
                    "source_type": "ai",
                    "source_bot_name": "GPTBot",
                },
            )
            assert event.status_code == 200

            snapshot = client.get(f"/api/v1/attribution/snapshot?org_id={org_id}&period_days=30")
            assert snapshot.status_code == 200
            assert snapshot.json()["conversions_total"] >= 1

            save_snapshot = client.post(f"/api/v1/attribution/snapshot?org_id={org_id}&period_days=30")
            assert save_snapshot.status_code == 200

    finally:
        asyncio.run(_cleanup(prefix))


def test_member_cannot_create_query_set_or_save_snapshot():
    prefix = f"pytest_innov_perm_{uuid.uuid4().hex[:8]}_"
    owner_email = f"{prefix}owner@example.com"
    member_email = f"{prefix}member@example.com"

    try:
        with TestClient(app) as register_client:
            owner_register = register_client.post(
                "/auth/register",
                data={"email": owner_email, "password": PASSWORD, "full_name": "Owner"},
                follow_redirects=False,
            )
            member_register = register_client.post(
                "/auth/register",
                data={"email": member_email, "password": PASSWORD, "full_name": "Member"},
                follow_redirects=False,
            )
            assert owner_register.status_code == 303
            assert member_register.status_code == 303

        owner_org_id = asyncio.run(_get_org_id_by_email(owner_email))
        member_user = asyncio.run(_get_user_by_email(member_email))
        assert owner_org_id is not None
        assert member_user is not None and member_user.id is not None
        asyncio.run(_add_member_to_org(owner_org_id, member_user.id, role="member"))

        with TestClient(app) as member_client:
            login = member_client.post(
                "/auth/login",
                data={"username": member_email, "password": PASSWORD},
                follow_redirects=False,
            )
            assert login.status_code == 303

            create_query_set = member_client.post(
                f"/api/v1/answer-capture/query-sets?org_id={owner_org_id}",
                json={"name": "Should fail"},
            )
            assert create_query_set.status_code == 403

            save_snapshot = member_client.post(
                f"/api/v1/attribution/snapshot?org_id={owner_org_id}&period_days=30"
            )
            assert save_snapshot.status_code == 403
    finally:
        asyncio.run(_cleanup(prefix))
