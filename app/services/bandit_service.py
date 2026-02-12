import json
import random
from datetime import datetime
from typing import Any, Optional

from sqlmodel import and_, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.innovation_plus import OptimizationBanditArm, OptimizationBanditDecision
from app.models.optimization import OptimizationAction


class BanditService:
    def _arm_key(self, action_id: int) -> str:
        return f"optimization_action:{action_id}"

    async def _get_pending_actions(
        self,
        session: AsyncSession,
        org_id: int,
        site_id: int,
    ) -> list[OptimizationAction]:
        rows = await session.exec(
            select(OptimizationAction)
            .where(
                and_(
                    OptimizationAction.org_id == org_id,
                    OptimizationAction.site_id == site_id,
                    OptimizationAction.status == "pending",
                )
            )
            .order_by(OptimizationAction.created_at.asc())
        )
        return rows.all()

    async def ensure_arms_for_site(
        self,
        session: AsyncSession,
        org_id: int,
        site_id: int,
    ) -> list[OptimizationBanditArm]:
        actions = await self._get_pending_actions(session, org_id, site_id)
        if not actions:
            return []

        existing = (
            await session.exec(
                select(OptimizationBanditArm).where(
                    and_(
                        OptimizationBanditArm.org_id == org_id,
                        OptimizationBanditArm.site_id == site_id,
                    )
                )
            )
        ).all()
        by_action_id = {row.action_id: row for row in existing}

        created: list[OptimizationBanditArm] = []
        for action in actions:
            if action.id in by_action_id:
                continue
            row = OptimizationBanditArm(
                org_id=org_id,
                site_id=site_id,
                action_id=action.id,
                arm_key=self._arm_key(action.id),
            )
            session.add(row)
            created.append(row)

        if created:
            await session.commit()
            for row in created:
                await session.refresh(row)
            existing.extend(created)

        return [row for row in existing if row.action_id in {a.id for a in actions}]

    def _score_arm(self, arm: OptimizationBanditArm, strategy: str) -> float:
        if strategy == "ucb":
            total_pulls = max(arm.pulls, 1)
            exploration = (2.0 * (1.0 / total_pulls)) ** 0.5
            return arm.average_reward + exploration
        # default thompson sampling
        alpha = max(arm.alpha, 0.001)
        beta = max(arm.beta, 0.001)
        return random.betavariate(alpha, beta)

    async def decide_next_action(
        self,
        session: AsyncSession,
        org_id: int,
        site_id: int,
        created_by_user_id: int,
        strategy: str = "thompson",
        context: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        strategy_name = (strategy or "thompson").strip().lower()
        if strategy_name not in {"thompson", "ucb"}:
            strategy_name = "thompson"

        actions = await self._get_pending_actions(session, org_id, site_id)
        if not actions:
            return {"selected_action": None, "scored_candidates": [], "strategy": strategy_name}

        action_by_id = {row.id: row for row in actions}
        arms = await self.ensure_arms_for_site(session, org_id, site_id)

        scored_candidates: list[dict[str, Any]] = []
        for arm in arms:
            action = action_by_id.get(arm.action_id)
            if not action:
                continue
            score = self._score_arm(arm, strategy_name)
            scored_candidates.append(
                {
                    "action_id": action.id,
                    "arm_id": arm.id,
                    "arm_key": arm.arm_key,
                    "title": action.title,
                    "score": round(score, 6),
                    "pulls": arm.pulls,
                    "average_reward": arm.average_reward,
                    "alpha": arm.alpha,
                    "beta": arm.beta,
                }
            )

        scored_candidates = sorted(scored_candidates, key=lambda x: x["score"], reverse=True)
        selected = scored_candidates[0] if scored_candidates else None

        decision = OptimizationBanditDecision(
            org_id=org_id,
            site_id=site_id,
            created_by_user_id=created_by_user_id,
            selected_action_id=selected["action_id"] if selected else None,
            selected_arm_key=selected["arm_key"] if selected else None,
            strategy=strategy_name,
            scored_candidates_json=json.dumps(scored_candidates, ensure_ascii=True),
            context_json=json.dumps(context or {}, ensure_ascii=True),
        )
        session.add(decision)
        await session.commit()
        await session.refresh(decision)

        selected_action_id = selected["action_id"] if selected else None
        selected_action = None
        if selected_action_id is not None:
            selected_action = (
                await session.exec(
                    select(OptimizationAction).where(
                        and_(
                            OptimizationAction.id == selected_action_id,
                            OptimizationAction.org_id == org_id,
                            OptimizationAction.site_id == site_id,
                        )
                    )
                )
            ).first()

        return {
            "decision_id": decision.id,
            "strategy": strategy_name,
            "selected_action_id": selected_action_id,
            "selected_action": selected_action,
            "scored_candidates": scored_candidates,
        }

    async def record_feedback(
        self,
        session: AsyncSession,
        org_id: int,
        action_id: int,
        reward: float,
    ) -> OptimizationBanditArm:
        normalized_reward = max(0.0, min(1.0, float(reward)))
        arm = (
            await session.exec(
                select(OptimizationBanditArm).where(
                    and_(
                        OptimizationBanditArm.org_id == org_id,
                        OptimizationBanditArm.action_id == action_id,
                    )
                )
            )
        ).first()
        if not arm:
            action = (
                await session.exec(
                    select(OptimizationAction).where(
                        and_(
                            OptimizationAction.org_id == org_id,
                            OptimizationAction.id == action_id,
                        )
                    )
                )
            ).first()
            if not action:
                raise ValueError("Optimization action not found")
            arm = OptimizationBanditArm(
                org_id=org_id,
                site_id=action.site_id,
                action_id=action.id,
                arm_key=self._arm_key(action.id),
            )

        arm.pulls += 1
        arm.cumulative_reward += normalized_reward
        arm.average_reward = arm.cumulative_reward / max(arm.pulls, 1)
        arm.last_reward = normalized_reward
        arm.last_reward_at = datetime.utcnow()
        arm.alpha += normalized_reward
        arm.beta += 1.0 - normalized_reward
        arm.updated_at = datetime.utcnow()

        session.add(arm)
        await session.commit()
        await session.refresh(arm)
        return arm

    async def list_arms(
        self,
        session: AsyncSession,
        org_id: int,
        site_id: int,
    ) -> list[OptimizationBanditArm]:
        rows = await session.exec(
            select(OptimizationBanditArm)
            .where(
                and_(
                    OptimizationBanditArm.org_id == org_id,
                    OptimizationBanditArm.site_id == site_id,
                )
            )
            .order_by(OptimizationBanditArm.average_reward.desc(), OptimizationBanditArm.updated_at.desc())
        )
        return rows.all()


bandit_service = BanditService()
