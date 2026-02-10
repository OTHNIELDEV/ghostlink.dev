import asyncio
import uuid
from datetime import datetime, timedelta
import json

import pytest
from sqlmodel import select

from app.db.engine import get_session
from app.models.innovation import ProofSnapshot
from app.models.innovation_plus import OptimizationBanditArm
from app.models.optimization import OptimizationAction
from app.models.site import Site
from app.models.user import User
from app.models.organization import Membership, Organization
from app.services.optimization_service import optimization_service
from app.services.bandit_service import bandit_service


async def _create_test_context(prefix: str):
    async for session in get_session():
        # Create User & Org
        user = User(
            email=f"{prefix}user@example.com",
            full_name="Test User",
            hashed_password="hash",
            is_active=True,
            is_verified=True
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)

        org = Organization(
            name=f"{prefix} Org",
            slug=f"{prefix}-org",
            billing_email=f"{prefix}billing@example.com"
        )
        session.add(org)
        await session.commit()
        await session.refresh(org)

        membership = Membership(user_id=user.id, org_id=org.id, role="owner")
        session.add(membership)
        
        # Create Site
        site = Site(
            org_id=org.id,
            owner_id=user.id,
            url=f"https://{prefix}.example.com",
            status="active"
        )
        session.add(site)
        await session.commit()
        await session.refresh(site)
        
        return session, user, org, site


async def _cleanup(session, prefix):
    # Simplified cleanup for test isolation
    # In a real scenario, use a proper fixture or transaction rollback
    pass 


@pytest.mark.asyncio
async def _run_optimization_feedback_loop():
    prefix = f"opt_loop_{uuid.uuid4().hex[:8]}"
    
    # 1. Setup Context
    async for session in get_session():
        user = User(email=f"{prefix}@test.com", hashed_password="x")
        session.add(user)
        await session.commit()
        await session.refresh(user)
        
        org = Organization(name=prefix, slug=prefix, billing_email=f"{prefix}@test.com")
        session.add(org)
        await session.commit()
        await session.refresh(org)
        
        site = Site(org_id=org.id, url=f"https://{prefix}.com", owner_id=user.id)
        session.add(site)
        await session.commit()
        await session.refresh(site)

        try:
            # 2. Create an OptimizationAction and 'Apply' it
            action = OptimizationAction(
                org_id=org.id,
                site_id=site.id,
                title="Test Optimization",
                status="applied",
                loop_version="v1",
                applied_by_user_id=user.id,
                applied_at=datetime.utcnow() - timedelta(hours=1), # Applied 1 hour ago
                proposed_instruction="Optimized instruction",
                rationale="Test rationale"
            )
            session.add(action)
            await session.commit()
            await session.refresh(action)

            # Ensure Bandit Arm exists (usually created upon generation/display)
            # Here we manually create it to simulate the flow
            # First create as pending to ensure arm is created
            action.status = "pending"
            session.add(action)
            await session.commit()
            
            await bandit_service.ensure_arms_for_site(session, org.id, site.id)
            
            action.status = "applied"
            session.add(action)
            await session.commit()
            
            # Check arm again
            arms = await bandit_service.list_arms(session, org.id, site.id)
            target_arm = next((a for a in arms if a.action_id == action.id), None)
            assert target_arm is not None
            initial_pulls = target_arm.pulls

            # 3. Create baseline snapshot BEFORE application
            baseline_snapshot = ProofSnapshot(
                org_id=org.id,
                created_by_user_id=user.id,
                period_start=datetime.utcnow() - timedelta(hours=3),
                period_end=datetime.utcnow() - timedelta(hours=2),
                metadata_json=json.dumps({"proof_score": 40.0}),
                confidence_level="high",
                created_at=datetime.utcnow() - timedelta(hours=2),
            )
            session.add(baseline_snapshot)
            await session.commit()

            # 4. Create post-action snapshot AFTER application
            post_snapshot = ProofSnapshot(
                org_id=org.id,
                created_by_user_id=user.id,
                period_start=datetime.utcnow() - timedelta(minutes=30),
                period_end=datetime.utcnow(),
                metadata_json=json.dumps({"proof_score": 85.0}),
                confidence_level="high",
                created_at=datetime.utcnow(),
            )
            session.add(post_snapshot)
            await session.commit()

            # 5. Evaluate once (strict baseline-delta)
            evaluated_count = await optimization_service.evaluate_applied_actions(session, org.id)
            
            assert evaluated_count == 1

            # 6. Verify feedback and evaluation metadata
            await session.refresh(target_arm)
            assert target_arm.pulls == initial_pulls + 1
            assert target_arm.last_reward == 1.0
            arm_meta = json.loads(target_arm.metadata_json or "{}")
            auto_eval = arm_meta.get("auto_eval", {})
            assert auto_eval.get("mode") == "baseline_delta_v2"
            assert auto_eval.get("baseline_snapshot_id") == baseline_snapshot.id
            assert auto_eval.get("post_snapshot_id") == post_snapshot.id
            assert auto_eval.get("delta_proof_score") == 45.0

            # 7. Re-running evaluator should be idempotent for the same action
            evaluated_count_second = await optimization_service.evaluate_applied_actions(session, org.id)
            assert evaluated_count_second == 0
            await session.refresh(target_arm)
            assert target_arm.pulls == initial_pulls + 1
            
        finally:
            pass
            # Cleanup logic if needed


def test_optimization_feedback_loop():
    asyncio.run(_run_optimization_feedback_loop())
