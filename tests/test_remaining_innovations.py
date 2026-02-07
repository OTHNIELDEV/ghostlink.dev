import asyncio
import json
import uuid
from datetime import datetime

from fastapi.testclient import TestClient
from sqlmodel import select

from app.db.engine import get_session
from app.main import app
from app.models.billing import Subscription
from app.models.innovation_plus import (
    BrandEntity,
    BrandEntityRelation,
    ComplianceCheckRun,
    CompliancePolicy,
    EdgeArtifact,
    EdgeDeployment,
    OptimizationBanditArm,
    OptimizationBanditDecision,
    SchemaDraft,
)
from app.models.optimization import OptimizationAction
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
            seo_description="GhostLink baseline SEO description",
            llms_txt_content="GhostLink llms summary",
            json_ld_content=json.dumps({"@context": "https://schema.org", "@type": "WebSite", "name": "GhostLink"}),
            schema_type="WebSite",
            updated_at=datetime.utcnow(),
        )
        session.add(site)
        await session.commit()
        await session.refresh(site)
        return site


async def _create_action(org_id: int, site_id: int, title: str, instruction: str) -> OptimizationAction:
    async for session in get_session():
        row = OptimizationAction(
            org_id=org_id,
            site_id=site_id,
            title=title,
            proposed_instruction=instruction,
            source_recommendation=title,
            rationale="test",
            status="pending",
            loop_version="v1",
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return row


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
            deployments = (
                await session.exec(select(EdgeDeployment).where(EdgeDeployment.org_id.in_(org_ids)))
            ).all()
            for row in deployments:
                await session.delete(row)

            artifacts = (
                await session.exec(select(EdgeArtifact).where(EdgeArtifact.org_id.in_(org_ids)))
            ).all()
            for row in artifacts:
                await session.delete(row)

            checks = (
                await session.exec(select(ComplianceCheckRun).where(ComplianceCheckRun.org_id.in_(org_ids)))
            ).all()
            for row in checks:
                await session.delete(row)

            policies = (
                await session.exec(select(CompliancePolicy).where(CompliancePolicy.org_id.in_(org_ids)))
            ).all()
            for row in policies:
                await session.delete(row)

            drafts = (
                await session.exec(select(SchemaDraft).where(SchemaDraft.org_id.in_(org_ids)))
            ).all()
            for row in drafts:
                await session.delete(row)

            relations = (
                await session.exec(select(BrandEntityRelation).where(BrandEntityRelation.org_id.in_(org_ids)))
            ).all()
            for row in relations:
                await session.delete(row)

            entities = (
                await session.exec(select(BrandEntity).where(BrandEntity.org_id.in_(org_ids)))
            ).all()
            for row in entities:
                await session.delete(row)

            decisions = (
                await session.exec(select(OptimizationBanditDecision).where(OptimizationBanditDecision.org_id.in_(org_ids)))
            ).all()
            for row in decisions:
                await session.delete(row)

            arms = (
                await session.exec(select(OptimizationBanditArm).where(OptimizationBanditArm.org_id.in_(org_ids)))
            ).all()
            for row in arms:
                await session.delete(row)

            actions = (
                await session.exec(select(OptimizationAction).where(OptimizationAction.org_id.in_(org_ids)))
            ).all()
            for row in actions:
                await session.delete(row)

            sites = (
                await session.exec(select(Site).where(Site.org_id.in_(org_ids)))
            ).all()
            for row in sites:
                await session.delete(row)

            subscriptions = (
                await session.exec(select(Subscription).where(Subscription.org_id.in_(org_ids)))
            ).all()
            for row in subscriptions:
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


def test_remaining_innovations_end_to_end():
    prefix = f"pytest_remain_{uuid.uuid4().hex[:8]}_"
    owner_email = f"{prefix}owner@example.com"

    try:
        with TestClient(app) as client:
            register = client.post(
                "/auth/register",
                data={"email": owner_email, "password": PASSWORD, "full_name": "Remaining Owner"},
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
            assert site.id is not None

            action_blocked = asyncio.run(
                _create_action(org_id, site.id, "Blocked Action", "forbidden-term should not be used")
            )
            action_ok = asyncio.run(
                _create_action(org_id, site.id, "Safe Action", "Improve clarity for answer capture")
            )

            policy = client.post(
                f"/api/v1/compliance/policies?org_id={org_id}",
                json={
                    "name": "Block Forbidden Terms",
                    "enforcement_mode": "blocking",
                    "rules": {"banned_phrases": ["forbidden-term"]},
                },
            )
            assert policy.status_code == 200, policy.text

            blocked_approve = client.post(
                f"/api/v1/optimizations/actions/{action_blocked.id}/approve",
                params={"org_id": org_id},
            )
            assert blocked_approve.status_code == 409

            bandit_decide = client.post(
                f"/api/v1/optimizations/sites/{site.id}/actions/decide-v2",
                params={"org_id": org_id, "strategy": "thompson"},
            )
            assert bandit_decide.status_code == 200, bandit_decide.text
            selected = bandit_decide.json().get("selected_action")
            assert selected is not None

            feedback = client.post(
                f"/api/v1/optimizations/actions/{action_ok.id}/feedback",
                params={"org_id": org_id},
                json={"reward": 0.9, "notes": "High uplift"},
            )
            assert feedback.status_code == 200, feedback.text
            assert feedback.json()["arm"]["pulls"] >= 1

            org_entity = client.post(
                f"/api/v1/knowledge-graph/entities?org_id={org_id}",
                json={
                    "entity_type": "Organization",
                    "name": "GhostLink",
                    "attributes": {"url": "https://ghostlink.ai"},
                },
            )
            assert org_entity.status_code == 200, org_entity.text
            product_entity = client.post(
                f"/api/v1/knowledge-graph/entities?org_id={org_id}",
                json={
                    "entity_type": "Product",
                    "name": "GhostLink Pro",
                    "attributes": {"brand": "GhostLink"},
                },
            )
            assert product_entity.status_code == 200, product_entity.text

            rel = client.post(
                f"/api/v1/knowledge-graph/relations?org_id={org_id}",
                json={
                    "from_entity_id": org_entity.json()["id"],
                    "to_entity_id": product_entity.json()["id"],
                    "relation_type": "offers",
                },
            )
            assert rel.status_code == 200, rel.text

            draft = client.post(
                f"/api/v1/knowledge-graph/sites/{site.id}/schema-drafts?org_id={org_id}",
                json={"entity_ids": [org_entity.json()["id"], product_entity.json()["id"]]},
            )
            assert draft.status_code == 200, draft.text
            draft_id = draft.json()["id"]

            applied = client.post(
                f"/api/v1/knowledge-graph/schema-drafts/{draft_id}/apply",
                params={"org_id": org_id},
            )
            assert applied.status_code == 200, applied.text
            refreshed_site = asyncio.run(_get_site(site.id))
            assert refreshed_site is not None
            assert refreshed_site.schema_type == "GraphComposite"

            artifact_a = client.post(
                f"/api/v1/edge/sites/{site.id}/artifacts/build?org_id={org_id}",
                json={"artifact_type": "bridge_script"},
            )
            assert artifact_a.status_code == 200, artifact_a.text
            deploy_a = client.post(
                f"/api/v1/edge/sites/{site.id}/deployments?org_id={org_id}",
                json={"artifact_id": artifact_a.json()["id"], "channel": "production"},
            )
            assert deploy_a.status_code == 200, deploy_a.text

            artifact_b = client.post(
                f"/api/v1/edge/sites/{site.id}/artifacts/build?org_id={org_id}",
                json={"artifact_type": "jsonld"},
            )
            assert artifact_b.status_code == 200, artifact_b.text
            deploy_b = client.post(
                f"/api/v1/edge/sites/{site.id}/deployments?org_id={org_id}",
                json={"artifact_id": artifact_b.json()["id"], "channel": "production"},
            )
            assert deploy_b.status_code == 200, deploy_b.text

            rollback = client.post(
                f"/api/v1/edge/sites/{site.id}/deployments/{deploy_a.json()['id']}/rollback?org_id={org_id}",
                json={"metadata": {"reason": "test-rollback"}},
            )
            assert rollback.status_code == 200, rollback.text
            assert rollback.json()["artifact_id"] == artifact_a.json()["id"]
    finally:
        asyncio.run(_cleanup(prefix))
