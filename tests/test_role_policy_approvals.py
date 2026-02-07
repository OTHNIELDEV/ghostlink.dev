import asyncio
import json
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

from app.db.engine import get_session
from app.main import app
from app.models.approval import ApprovalRequest
from app.models.billing import Subscription
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


async def _get_approval(approval_id: int) -> ApprovalRequest | None:
    async for session in get_session():
        return (await session.exec(select(ApprovalRequest).where(ApprovalRequest.id == approval_id))).first()


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
            approvals = (
                await session.exec(select(ApprovalRequest).where(ApprovalRequest.org_id.in_(org_ids)))
            ).all()
            for approval in approvals:
                await session.delete(approval)

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
def approval_prefix() -> str:
    prefix = f"pytest_approval_{uuid.uuid4().hex[:8]}_"
    try:
        yield prefix
    finally:
        asyncio.run(_cleanup(prefix))


def test_role_policy_and_approval_flow_for_billing(approval_prefix: str):
    owner_email = f"{approval_prefix}owner@example.com"
    member_email = f"{approval_prefix}member@example.com"

    with TestClient(app) as register_client:
        owner_register = register_client.post(
            "/auth/register",
            data={"email": owner_email, "password": PASSWORD, "full_name": "Owner User"},
            follow_redirects=False,
        )
        member_register = register_client.post(
            "/auth/register",
            data={"email": member_email, "password": PASSWORD, "full_name": "Member User"},
            follow_redirects=False,
        )
        assert owner_register.status_code == 303
        assert member_register.status_code == 303

    owner_org_id = asyncio.run(_get_org_id_by_email(owner_email))
    owner_user = asyncio.run(_get_user_by_email(owner_email))
    member_user = asyncio.run(_get_user_by_email(member_email))
    assert owner_org_id is not None
    assert owner_user is not None and owner_user.id is not None
    assert member_user is not None and member_user.id is not None

    asyncio.run(_add_member_to_org(owner_org_id, member_user.id, role="member"))

    with TestClient(app) as member_client:
        login_member = member_client.post(
            "/auth/login",
            data={"username": member_email, "password": PASSWORD},
            follow_redirects=False,
        )
        assert login_member.status_code == 303

        forbidden_change = member_client.post(
            "/billing/checkout",
            data={"plan_code": "free", "org_id": str(owner_org_id), "interval": "month"},
        )
        assert forbidden_change.status_code == 403
        assert "owner/admin" in forbidden_change.json().get("detail", "")

        requested_change = member_client.post(
            "/billing/checkout",
            data={
                "plan_code": "free",
                "org_id": str(owner_org_id),
                "interval": "month",
                "request_approval": "true",
            },
        )
        assert requested_change.status_code == 202
        approval_payload = requested_change.json()
        assert approval_payload["status"] == "approval_requested"
        approval_id = approval_payload["approval_request_id"]

        api_key_manage = member_client.post(
            f"/api/api-keys?org_id={owner_org_id}",
            json={"name": "ShouldFail", "scopes": "read:write"},
        )
        assert api_key_manage.status_code == 403
        assert "owners/admins" in api_key_manage.json().get("detail", "")

    with TestClient(app) as owner_client:
        login_owner = owner_client.post(
            "/auth/login",
            data={"username": owner_email, "password": PASSWORD},
            follow_redirects=False,
        )
        assert login_owner.status_code == 303

        pending_requests = owner_client.get(
            f"/api/v1/approvals?org_id={owner_org_id}&status=pending"
        )
        assert pending_requests.status_code == 200
        pending_ids = [row["id"] for row in pending_requests.json()["approvals"]]
        assert approval_id in pending_ids

        approved = owner_client.post(
            f"/api/v1/approvals/{approval_id}/approve",
            params={"org_id": owner_org_id},
        )
        assert approved.status_code == 200
        assert approved.json()["status"] == "approved"

    approval_row = asyncio.run(_get_approval(approval_id))
    assert approval_row is not None
    assert approval_row.status == "approved"
    assert approval_row.reviewed_by_user_id == owner_user.id

    parsed_result = {}
    if approval_row.execution_result:
        parsed_result = json.loads(approval_row.execution_result)
    assert parsed_result.get("status") in {"applied", "checkout_required"}
