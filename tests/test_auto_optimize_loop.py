import asyncio
import json
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

from app.db.engine import get_session
from app.main import app
from app.models.billing import Subscription
from app.models.optimization import OptimizationAction
from app.models.organization import Membership, Organization
from app.models.site import Site
from app.models.user import User
import app.routers.optimizations as optimizations_router


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
            url=url,
            status="completed",
            org_id=org_id,
            owner_id=owner_id,
            ai_score=72,
            ai_analysis_json=json.dumps(
                {
                    "recommendations": [
                        "Add concrete pricing examples to improve answerability.",
                        "Use explicit entity names in H1 and section headers.",
                    ]
                }
            ),
        )
        session.add(site)
        await session.commit()
        await session.refresh(site)
        return site


async def _get_action(action_id: int) -> OptimizationAction | None:
    async for session in get_session():
        return (await session.exec(select(OptimizationAction).where(OptimizationAction.id == action_id))).first()


async def _get_site(site_id: int) -> Site | None:
    async for session in get_session():
        return (await session.exec(select(Site).where(Site.id == site_id))).first()


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
            actions = (
                await session.exec(select(OptimizationAction).where(OptimizationAction.org_id.in_(org_ids)))
            ).all()
            for action in actions:
                await session.delete(action)

            sites = (await session.exec(select(Site).where(Site.org_id.in_(org_ids)))).all()
            for site in sites:
                await session.delete(site)

            subscriptions = (
                await session.exec(select(Subscription).where(Subscription.org_id.in_(org_ids)))
            ).all()
            for subscription in subscriptions:
                await session.delete(subscription)

            memberships_by_org = (
                await session.exec(select(Membership).where(Membership.org_id.in_(org_ids)))
            ).all()
            for membership in memberships_by_org:
                await session.delete(membership)

            for org in orgs:
                await session.delete(org)

        if user_ids:
            memberships_by_user = (
                await session.exec(select(Membership).where(Membership.user_id.in_(user_ids)))
            ).all()
            for membership in memberships_by_user:
                await session.delete(membership)

        for user in users:
            await session.delete(user)

        await session.commit()
        break


@pytest.fixture
def optimize_prefix() -> str:
    prefix = f"pytest_opt_{uuid.uuid4().hex[:8]}_"
    try:
        yield prefix
    finally:
        asyncio.run(_cleanup(prefix))


def test_auto_optimize_loop_generate_approve_reject(optimize_prefix: str, monkeypatch: pytest.MonkeyPatch):
    email = f"{optimize_prefix}owner@example.com"

    async def fake_process_site_background(_site_id: int, language: str = "English"):
        return None

    monkeypatch.setattr(optimizations_router, "process_site_background", fake_process_site_background)

    with TestClient(app) as client:
        register = client.post(
            "/auth/register",
            data={"email": email, "password": PASSWORD, "full_name": "Optimize Owner"},
            follow_redirects=False,
        )
        assert register.status_code == 303

        org_id = asyncio.run(_get_org_id_by_email(email))
        user = asyncio.run(_get_user_by_email(email))
        assert org_id is not None
        assert user is not None and user.id is not None

        site = asyncio.run(_create_site(org_id=org_id, owner_id=user.id, url=f"https://{optimize_prefix}site.example"))
        assert site.id is not None

        generated = client.post(
            f"/api/v1/optimizations/sites/{site.id}/actions/generate",
            params={"org_id": org_id},
        )
        assert generated.status_code == 200
        payload = generated.json()
        assert payload["created_count"] >= 1
        assert len(payload["actions"]) >= 1

        listed = client.get(
            f"/api/v1/optimizations/sites/{site.id}/actions",
            params={"org_id": org_id},
        )
        assert listed.status_code == 200
        listed_actions = listed.json()["actions"]
        assert listed_actions

        first_action_id = listed_actions[0]["id"]
        approve = client.post(
            f"/api/v1/optimizations/actions/{first_action_id}/approve",
            params={"org_id": org_id},
        )
        assert approve.status_code == 200
        assert approve.json()["status"] == "applied"

        applied_action = asyncio.run(_get_action(first_action_id))
        assert applied_action is not None
        assert applied_action.status == "applied"

        updated_site = asyncio.run(_get_site(site.id))
        assert updated_site is not None
        assert updated_site.status == "processing"
        assert updated_site.custom_instruction is not None
        assert "Auto-Optimize Loop v1 Actions:" in updated_site.custom_instruction

        second_actions = client.get(
            f"/api/v1/optimizations/sites/{site.id}/actions",
            params={"org_id": org_id},
        ).json()["actions"]
        pending = [a for a in second_actions if a["status"] == "pending"]
        if pending:
            reject = client.post(
                f"/api/v1/optimizations/actions/{pending[0]['id']}/reject",
                params={"org_id": org_id},
            )
            assert reject.status_code == 200
            assert reject.json()["status"] == "rejected"
