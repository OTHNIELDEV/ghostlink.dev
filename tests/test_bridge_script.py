import asyncio
import json
import uuid

from fastapi.testclient import TestClient
from sqlmodel import select

from app.db.engine import get_session
from app.main import app
from app.models.analytics import BotVisit, BridgeEvent
from app.models.billing import Subscription
from app.models.organization import Membership, Organization
from app.models.site import Site
from app.models.user import User
from app.routers.bridge import _build_bridge_token


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
            json_ld_content=json.dumps({"@context": "https://schema.org", "@type": "WebSite", "name": "Bridge Test"}),
            schema_type="WebSite",
        )
        session.add(site)
        await session.commit()
        await session.refresh(site)
        return site


async def _list_bridge_events(site_id: int) -> list[BridgeEvent]:
    async for session in get_session():
        return (
            await session.exec(
                select(BridgeEvent).where(BridgeEvent.site_id == site_id)
            )
        ).all()


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
            subscriptions = (
                await session.exec(select(Subscription).where(Subscription.org_id.in_(org_ids)))
            ).all()
            for row in subscriptions:
                await session.delete(row)

            sites = (await session.exec(select(Site).where(Site.org_id.in_(org_ids)))).all()
            site_ids = [s.id for s in sites if s.id is not None]

            if site_ids:
                bridge_events = (
                    await session.exec(select(BridgeEvent).where(BridgeEvent.site_id.in_(site_ids)))
                ).all()
                for row in bridge_events:
                    await session.delete(row)

                bot_visits = (
                    await session.exec(select(BotVisit).where(BotVisit.site_id.in_(site_ids)))
                ).all()
                for row in bot_visits:
                    await session.delete(row)

                for row in sites:
                    await session.delete(row)

            memberships = (
                await session.exec(select(Membership).where(Membership.org_id.in_(org_ids)))
            ).all()
            for row in memberships:
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


def test_bridge_script_collects_human_events():
    prefix = f"pytest_bridge_{uuid.uuid4().hex[:8]}_"
    owner_email = f"{prefix}owner@example.com"

    try:
        with TestClient(app) as client:
            register = client.post(
                "/auth/register",
                data={"email": owner_email, "password": PASSWORD, "full_name": "Bridge Owner"},
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
            owner = asyncio.run(_get_user_by_email(owner_email))
            assert org_id is not None
            assert owner is not None and owner.id is not None

            site = asyncio.run(_create_site(org_id, owner.id, f"https://{prefix}site.example"))
            assert site.script_id
            assert site.id is not None

            script_response = client.get(
                f"/api/bridge/{site.script_id}.js",
                headers={"user-agent": "Mozilla/5.0 BridgeTest"},
            )
            assert script_response.status_code == 200
            assert "sendEvent('pageview')" in script_response.text
            assert "const endpoint = decode(" in script_response.text
            assert "tokenSig" in script_response.text

            token_exp, token_nonce, token_sig = _build_bridge_token(site.script_id)
            event_response = client.get(
                f"/api/bridge/{site.script_id}/event",
                params={
                    "e": "pageview",
                    "sid": "test-session",
                    "p": "/pricing?src=test",
                    "t": "Pricing",
                    "r": "https://google.com",
                    "lang": "ko-KR",
                    "tz": "Asia/Seoul",
                    "vp": "1920x1080",
                    "gx": str(token_exp),
                    "gn": token_nonce,
                    "gs": token_sig,
                },
                headers={
                    "user-agent": "Mozilla/5.0 BridgeTest",
                    "referer": f"{site.url}/pricing",
                },
            )
            assert event_response.status_code == 204

            invalid_event = client.get(
                f"/api/bridge/{site.script_id}/event",
                params={
                    "e": "pageview",
                    "sid": "bad-session",
                    "p": "/",
                    "gx": "123",
                    "gn": "bad",
                    "gs": "bad-signature",
                },
                headers={"referer": "https://evil.example/"},
            )
            assert invalid_event.status_code == 403

            events = asyncio.run(_list_bridge_events(site.id))
            assert len(events) >= 1
            assert any(e.event_type == "pageview" and e.page_url == "/pricing?src=test" for e in events)
    finally:
        asyncio.run(_cleanup(prefix))
