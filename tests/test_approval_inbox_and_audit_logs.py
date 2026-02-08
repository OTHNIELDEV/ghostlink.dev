import asyncio
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

from app.db.engine import get_session
from app.main import app
from app.models.approval import ApprovalRequest
from app.models.audit_log import AuditLog
from app.models.billing import Subscription, UsageRecord
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


async def _get_latest_site_id_by_org(org_id: int) -> int | None:
    async for session in get_session():
        row = (
            await session.exec(
                select(Site.id)
                .where(Site.org_id == org_id)
                .order_by(Site.id.desc())
            )
        ).first()
        return row


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
            usage_rows = (
                await session.exec(select(UsageRecord).where(UsageRecord.org_id.in_(org_ids)))
            ).all()
            for row in usage_rows:
                await session.delete(row)

            sites = (
                await session.exec(select(Site).where(Site.org_id.in_(org_ids)))
            ).all()
            for row in sites:
                await session.delete(row)

            audit_logs = (
                await session.exec(select(AuditLog).where(AuditLog.org_id.in_(org_ids)))
            ).all()
            for row in audit_logs:
                await session.delete(row)

            approvals = (
                await session.exec(select(ApprovalRequest).where(ApprovalRequest.org_id.in_(org_ids)))
            ).all()
            for row in approvals:
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


@pytest.fixture
def inbox_prefix() -> str:
    prefix = f"pytest_inbox_{uuid.uuid4().hex[:8]}_"
    try:
        yield prefix
    finally:
        asyncio.run(_cleanup(prefix))


def test_dashboard_and_approvals_page_show_pending_inbox(inbox_prefix: str):
    owner_email = f"{inbox_prefix}owner@example.com"
    member_email = f"{inbox_prefix}member@example.com"

    with TestClient(app) as register_client:
        owner_register = register_client.post(
            "/auth/register",
            data={"email": owner_email, "password": PASSWORD, "full_name": "Owner Inbox"},
            follow_redirects=False,
        )
        member_register = register_client.post(
            "/auth/register",
            data={"email": member_email, "password": PASSWORD, "full_name": "Member Inbox"},
            follow_redirects=False,
        )
        assert owner_register.status_code == 303
        assert member_register.status_code == 303

    org_id = asyncio.run(_get_org_id_by_email(owner_email))
    owner_user = asyncio.run(_get_user_by_email(owner_email))
    member_user = asyncio.run(_get_user_by_email(member_email))
    assert org_id is not None
    assert owner_user is not None and owner_user.id is not None
    assert member_user is not None and member_user.id is not None

    asyncio.run(_add_member_to_org(org_id, member_user.id, role="member"))

    with TestClient(app) as member_client:
        login_member = member_client.post(
            "/auth/login",
            data={"username": member_email, "password": PASSWORD},
            follow_redirects=False,
        )
        assert login_member.status_code == 303

        request_change = member_client.post(
            "/billing/checkout",
            data={
                "plan_code": "free",
                "org_id": str(org_id),
                "interval": "month",
                "request_approval": "true",
            },
        )
        assert request_change.status_code == 202
        approval_id = request_change.json()["approval_request_id"]

    with TestClient(app) as owner_client:
        login_owner = owner_client.post(
            "/auth/login",
            data={"username": owner_email, "password": PASSWORD},
            follow_redirects=False,
        )
        assert login_owner.status_code == 303

        dashboard = owner_client.get(f"/dashboard?org_id={org_id}")
        assert dashboard.status_code == 200
        assert "Pending Approval Inbox" in dashboard.text
        assert f"/approvals?org_id={org_id}" in dashboard.text

        add_site = owner_client.post(
            "/api/sites",
            data={"url": f"https://{inbox_prefix}dash.example", "org_id": str(org_id)},
        )
        assert add_site.status_code == 200
        site_id = asyncio.run(_get_latest_site_id_by_org(org_id))
        assert site_id is not None

        dashboard_with_site = owner_client.get(f"/dashboard?org_id={org_id}")
        assert dashboard_with_site.status_code == 200
        assert f"/api/sites/{site_id}/generate?org_id={org_id}" in dashboard_with_site.text

        row_response = owner_client.get(f"/api/sites/{site_id}/row", params={"org_id": org_id})
        assert row_response.status_code == 200

        inbox = owner_client.get(f"/approvals?org_id={org_id}")
        assert inbox.status_code == 200
        assert "Approval Inbox" in inbox.text
        assert f"#{approval_id}" in inbox.text


def test_audit_logs_permissions_and_events(inbox_prefix: str):
    owner_email = f"{inbox_prefix}owner2@example.com"
    member_email = f"{inbox_prefix}member2@example.com"

    with TestClient(app) as register_client:
        owner_register = register_client.post(
            "/auth/register",
            data={"email": owner_email, "password": PASSWORD, "full_name": "Owner Audit"},
            follow_redirects=False,
        )
        member_register = register_client.post(
            "/auth/register",
            data={"email": member_email, "password": PASSWORD, "full_name": "Member Audit"},
            follow_redirects=False,
        )
        assert owner_register.status_code == 303
        assert member_register.status_code == 303

    org_id = asyncio.run(_get_org_id_by_email(owner_email))
    owner_user = asyncio.run(_get_user_by_email(owner_email))
    member_user = asyncio.run(_get_user_by_email(member_email))
    assert org_id is not None
    assert owner_user is not None and owner_user.id is not None
    assert member_user is not None and member_user.id is not None

    asyncio.run(_add_member_to_org(org_id, member_user.id, role="member"))

    with TestClient(app) as member_client:
        login_member = member_client.post(
            "/auth/login",
            data={"username": member_email, "password": PASSWORD},
            follow_redirects=False,
        )
        assert login_member.status_code == 303

        request_change = member_client.post(
            "/billing/checkout",
            data={
                "plan_code": "free",
                "org_id": str(org_id),
                "interval": "month",
                "request_approval": "true",
            },
        )
        assert request_change.status_code == 202
        approval_id = request_change.json()["approval_request_id"]

        member_logs = member_client.get(f"/api/v1/audit-logs?org_id={org_id}")
        assert member_logs.status_code == 403

    with TestClient(app) as owner_client:
        login_owner = owner_client.post(
            "/auth/login",
            data={"username": owner_email, "password": PASSWORD},
            follow_redirects=False,
        )
        assert login_owner.status_code == 303

        approved = owner_client.post(
            f"/api/v1/approvals/{approval_id}/approve",
            params={"org_id": org_id},
        )
        assert approved.status_code == 200
        assert approved.json()["status"] == "approved"

        logs_response = owner_client.get(f"/api/v1/audit-logs?org_id={org_id}")
        assert logs_response.status_code == 200
        logs = logs_response.json()["logs"]
        actions = {row["action"] for row in logs}
        assert "approval.requested" in actions
        assert "approval.approved" in actions

        approved_only = owner_client.get(
            f"/api/v1/audit-logs?org_id={org_id}&action=approval.approved"
        )
        assert approved_only.status_code == 200
        filtered = approved_only.json()["logs"]
        assert filtered
        assert all(row["action"] == "approval.approved" for row in filtered)


def test_enterprise_approval_executes_contact_flow(inbox_prefix: str):
    owner_email = f"{inbox_prefix}owner3@example.com"
    member_email = f"{inbox_prefix}member3@example.com"

    with TestClient(app) as register_client:
        owner_register = register_client.post(
            "/auth/register",
            data={"email": owner_email, "password": PASSWORD, "full_name": "Owner Enterprise"},
            follow_redirects=False,
        )
        member_register = register_client.post(
            "/auth/register",
            data={"email": member_email, "password": PASSWORD, "full_name": "Member Enterprise"},
            follow_redirects=False,
        )
        assert owner_register.status_code == 303
        assert member_register.status_code == 303

    org_id = asyncio.run(_get_org_id_by_email(owner_email))
    member_user = asyncio.run(_get_user_by_email(member_email))
    assert org_id is not None
    assert member_user is not None and member_user.id is not None
    asyncio.run(_add_member_to_org(org_id, member_user.id, role="member"))

    with TestClient(app) as member_client:
        member_login = member_client.post(
            "/auth/login",
            data={"username": member_email, "password": PASSWORD},
            follow_redirects=False,
        )
        assert member_login.status_code == 303

        request_enterprise = member_client.post(
            "/billing/checkout",
            data={
                "plan_code": "enterprise",
                "org_id": str(org_id),
                "interval": "month",
                "request_approval": "true",
            },
        )
        assert request_enterprise.status_code == 202
        approval_id = request_enterprise.json()["approval_request_id"]

    with TestClient(app) as owner_client:
        owner_login = owner_client.post(
            "/auth/login",
            data={"username": owner_email, "password": PASSWORD},
            follow_redirects=False,
        )
        assert owner_login.status_code == 303

        approved = owner_client.post(
            f"/api/v1/approvals/{approval_id}/approve",
            params={"org_id": org_id},
        )
        assert approved.status_code == 200
        payload = approved.json()
        assert payload["status"] == "approved"
        assert payload["execution_result"]["status"] == "contact_required"
