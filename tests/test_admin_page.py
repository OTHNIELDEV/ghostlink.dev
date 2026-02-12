import asyncio
import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

from app.db.engine import get_session
from app.main import app
from app.models.billing import Subscription
from app.models.organization import Membership, Organization
from app.models.user import User
from app.routers.users import get_current_user


PASSWORD = "Passw0rd!@#"


async def _superuser():
    return SimpleNamespace(
        id=1,
        email="admin@example.com",
        full_name="Admin",
        preferred_ui_language="auto",
        is_superuser=True,
        is_active=True,
    )


async def _normal_user():
    return SimpleNamespace(
        id=2,
        email="member@example.com",
        full_name="Member",
        preferred_ui_language="auto",
        is_superuser=False,
        is_active=True,
    )


async def _get_org_id_by_email(email: str) -> int | None:
    async for session in get_session():
        user = (await session.exec(select(User).where(User.email == email))).first()
        if not user:
            return None
        membership = (await session.exec(select(Membership).where(Membership.user_id == user.id))).first()
        return membership.org_id if membership else None


async def _cleanup(prefix: str) -> None:
    async for session in get_session():
        users = (await session.exec(select(User).where(User.email.like(f"{prefix}%@example.com")))).all()
        user_ids = [u.id for u in users if u.id is not None]
        orgs = (
            await session.exec(
                select(Organization).where(Organization.billing_email.like(f"{prefix}%@example.com"))
            )
        ).all()
        org_ids = [o.id for o in orgs if o.id is not None]

        if org_ids:
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
def admin_prefix() -> str:
    prefix = f"pytest_admin_{uuid.uuid4().hex[:8]}_"
    try:
        yield prefix
    finally:
        asyncio.run(_cleanup(prefix))


def test_admin_page_requires_admin_access():
    app.dependency_overrides[get_current_user] = _normal_user
    try:
        with TestClient(app) as client:
            response = client.get("/admin")
        assert response.status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_admin_page_renders_for_superuser():
    app.dependency_overrides[get_current_user] = _superuser
    try:
        with TestClient(app) as client:
            response = client.get("/admin")
        assert response.status_code == 200
        assert "Admin CRM" in response.text
        assert "Organization CRM + Billing" in response.text
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_org_admin_scope_only_shows_org_users(admin_prefix: str):
    owner_a = f"{admin_prefix}ownera@example.com"
    owner_b = f"{admin_prefix}ownerb@example.com"

    with TestClient(app) as client_a:
        reg_a = client_a.post(
            "/auth/register",
            data={"email": owner_a, "password": PASSWORD, "full_name": "Owner A"},
            follow_redirects=False,
        )
        assert reg_a.status_code == 303

        org_a_id = asyncio.run(_get_org_id_by_email(owner_a))
        assert org_a_id is not None

        with TestClient(app) as client_b:
            reg_b = client_b.post(
                "/auth/register",
                data={"email": owner_b, "password": PASSWORD, "full_name": "Owner B"},
                follow_redirects=False,
            )
            assert reg_b.status_code == 303

        response = client_a.get("/admin", params={"org_id": org_a_id})
        assert response.status_code == 200
        assert owner_a in response.text
        assert owner_b not in response.text
