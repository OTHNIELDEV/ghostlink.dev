import json
from datetime import datetime
from typing import Any

from sqlmodel import and_, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.optimization import OptimizationAction
from app.models.site import Site


from app.models.innovation import ProofSnapshot
from app.models.innovation_plus import OptimizationBanditArm
from app.services.bandit_service import bandit_service


class OptimizationService:
    def _parse_json_dict(self, raw: str | None) -> dict[str, Any]:
        if not raw:
            return {}
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}

    def _snapshot_proof_score(self, snapshot: ProofSnapshot | None) -> float:
        if not snapshot:
            return 0.0
        if snapshot.metadata_json:
            try:
                meta = json.loads(snapshot.metadata_json)
                score = float(meta.get("proof_score", 0.0))
                return round(max(0.0, min(score, 100.0)), 1)
            except Exception:
                pass
        derived = (
            float(snapshot.answer_capture_rate_pct or 0.0) * 0.35
            + float(snapshot.citation_rate_pct or 0.0) * 0.35
            + float(snapshot.ai_assist_rate_pct or 0.0) * 0.30
        )
        return round(max(0.0, min(derived, 100.0)), 1)

    def _confidence_weight(self, level: str | None) -> float:
        mapping = {
            "high": 1.0,
            "medium": 0.85,
            "low": 0.7,
        }
        return mapping.get(str(level or "").strip().lower(), 0.7)

    def _reward_from_delta(self, delta_proof_score: float) -> float:
        if delta_proof_score >= 8.0:
            return 1.0
        if delta_proof_score >= 4.0:
            return 0.75
        if delta_proof_score >= 1.0:
            return 0.5
        if delta_proof_score >= 0.0:
            return 0.3
        return 0.0

    def _extract_recommendations(self, site: Site) -> list[str]:
        if not site.ai_analysis_json:
            return []

        try:
            analysis = json.loads(site.ai_analysis_json)
        except Exception:
            return []

        recommendations = analysis.get("recommendations", [])
        if not isinstance(recommendations, list):
            return []

        cleaned: list[str] = []
        for rec in recommendations:
            rec_str = str(rec).strip()
            if rec_str:
                cleaned.append(rec_str[:300])
        return cleaned

    def _build_instruction(self, recommendation: str) -> str:
        return f"Prioritize this optimization on the next scan: {recommendation}"

    async def list_actions(
        self,
        session: AsyncSession,
        site_id: int,
        org_id: int,
        include_closed: bool = False,
    ) -> list[OptimizationAction]:
        query = select(OptimizationAction).where(
            and_(
                OptimizationAction.site_id == site_id,
                OptimizationAction.org_id == org_id,
            )
        )
        if not include_closed:
            query = query.where(OptimizationAction.status.in_(["pending", "approved", "applied"]))
        query = query.order_by(OptimizationAction.created_at.desc())
        result = await session.exec(query)
        return result.all()

    async def generate_actions_for_site(
        self,
        session: AsyncSession,
        site: Site,
        org_id: int,
        max_items: int = 3,
    ) -> list[OptimizationAction]:
        recommendations = self._extract_recommendations(site)
        if not recommendations:
            recommendations = [
                "Improve entity clarity in headings and section titles for LLM retrieval.",
                "Add concrete product/service outcomes and pricing hints to improve answerability.",
            ]

        existing_result = await session.exec(
            select(OptimizationAction).where(
                and_(
                    OptimizationAction.site_id == site.id,
                    OptimizationAction.org_id == org_id,
                    OptimizationAction.status.in_(["pending", "approved", "applied"]),
                )
            )
        )
        existing = existing_result.all()
        existing_by_source = {action.source_recommendation for action in existing if action.source_recommendation}

        created: list[OptimizationAction] = []
        for recommendation in recommendations[:max_items]:
            if recommendation in existing_by_source:
                continue

            action = OptimizationAction(
                site_id=site.id,
                org_id=org_id,
                title=recommendation[:100],
                source_recommendation=recommendation,
                proposed_instruction=self._build_instruction(recommendation),
                rationale="Generated from latest AI analysis recommendations.",
                status="pending",
                loop_version="v1",
            )
            session.add(action)
            created.append(action)

        if created:
            await session.commit()
            for action in created:
                await session.refresh(action)

        return created

    async def get_action(
        self,
        session: AsyncSession,
        action_id: int,
        org_id: int,
    ) -> OptimizationAction | None:
        result = await session.exec(
            select(OptimizationAction).where(
                and_(
                    OptimizationAction.id == action_id,
                    OptimizationAction.org_id == org_id,
                )
            )
        )
        return result.first()

    async def reject_action(
        self,
        session: AsyncSession,
        action: OptimizationAction,
        user_id: int,
    ) -> OptimizationAction:
        action.status = "rejected"
        action.decided_by_user_id = user_id
        action.decided_at = datetime.utcnow()
        action.updated_at = datetime.utcnow()
        session.add(action)
        await session.commit()
        await session.refresh(action)
        return action

    async def approve_and_apply_action(
        self,
        session: AsyncSession,
        action: OptimizationAction,
        user_id: int,
    ) -> Site:
        site = await session.get(Site, action.site_id)
        if not site:
            action.status = "failed"
            action.error_msg = "Site not found"
            action.updated_at = datetime.utcnow()
            session.add(action)
            await session.commit()
            raise ValueError("Site not found for action")

        action.status = "approved"
        action.decided_by_user_id = user_id
        action.decided_at = datetime.utcnow()

        marker = action.proposed_instruction.strip()
        existing = (site.custom_instruction or "").strip()
        if marker not in existing:
            prefix = "Auto-Optimize Loop v1 Actions:\n"
            if not existing:
                site.custom_instruction = f"{prefix}- {marker}"
            else:
                if "Auto-Optimize Loop v1 Actions:" not in existing:
                    existing = f"{existing}\n\n{prefix}- {marker}"
                else:
                    existing = f"{existing}\n- {marker}"
                site.custom_instruction = existing

        action.status = "applied"
        action.applied_by_user_id = user_id
        action.applied_at = datetime.utcnow()
        action.updated_at = datetime.utcnow()

        site.status = "processing"
        site.updated_at = datetime.utcnow()

        session.add(site)
        session.add(action)
        await session.commit()
        await session.refresh(action)
        await session.refresh(site)
        return site

    async def evaluate_applied_actions(
        self,
        session: AsyncSession,
        org_id: int,
    ) -> int:
        """
        Periodically checks applied actions and awards rewards if Proof Scores improve.
        Returns count of actions evaluated.
        """
        actions = (
            await session.exec(
                select(OptimizationAction).where(
                    and_(
                        OptimizationAction.org_id == org_id,
                        OptimizationAction.status == "applied",
                    )
                )
            )
        ).all()

        evaluated_count = 0
        for action in actions:
            if not action.applied_at or action.id is None:
                continue

            arm = (
                await session.exec(
                    select(OptimizationBanditArm).where(
                        and_(
                            OptimizationBanditArm.org_id == org_id,
                            OptimizationBanditArm.action_id == action.id,
                        )
                    )
                )
            ).first()
            arm_meta = self._parse_json_dict(arm.metadata_json if arm else None)
            auto_eval_meta = arm_meta.get("auto_eval", {}) if isinstance(arm_meta.get("auto_eval"), dict) else {}
            if auto_eval_meta.get("post_snapshot_id") is not None:
                continue

            baseline_snapshot = (
                await session.exec(
                    select(ProofSnapshot)
                    .where(
                        and_(
                            ProofSnapshot.org_id == org_id,
                            ProofSnapshot.created_at <= action.applied_at,
                        )
                    )
                    .order_by(ProofSnapshot.created_at.desc())
                    .limit(1)
                )
            ).first()
            if not baseline_snapshot:
                continue

            post_snapshot = (
                await session.exec(
                    select(ProofSnapshot)
                    .where(
                        and_(
                            ProofSnapshot.org_id == org_id,
                            ProofSnapshot.created_at > action.applied_at,
                        )
                    )
                    .order_by(ProofSnapshot.created_at.asc())
                    .limit(1)
                )
            ).first()
            if not post_snapshot:
                continue

            baseline_score = self._snapshot_proof_score(baseline_snapshot)
            post_score = self._snapshot_proof_score(post_snapshot)
            delta_score = round(post_score - baseline_score, 1)
            raw_reward = self._reward_from_delta(delta_score)
            confidence_weight = min(
                self._confidence_weight(baseline_snapshot.confidence_level),
                self._confidence_weight(post_snapshot.confidence_level),
            )
            final_reward = round(max(0.0, min(raw_reward * confidence_weight, 1.0)), 3)

            updated_arm = await bandit_service.record_feedback(session, org_id, action.id, final_reward)
            updated_arm_meta = self._parse_json_dict(updated_arm.metadata_json)
            updated_arm_meta["auto_eval"] = {
                "mode": "baseline_delta_v2",
                "baseline_snapshot_id": baseline_snapshot.id,
                "baseline_proof_score": baseline_score,
                "baseline_confidence_level": baseline_snapshot.confidence_level,
                "post_snapshot_id": post_snapshot.id,
                "post_proof_score": post_score,
                "post_confidence_level": post_snapshot.confidence_level,
                "delta_proof_score": delta_score,
                "raw_reward": raw_reward,
                "confidence_weight": confidence_weight,
                "reward": final_reward,
                "evaluated_at": datetime.utcnow().isoformat(),
            }
            updated_arm.metadata_json = json.dumps(updated_arm_meta, ensure_ascii=True)
            session.add(updated_arm)
            await session.commit()
            evaluated_count += 1

        return evaluated_count

    async def build_action_impact_summary(
        self,
        session: AsyncSession,
        org_id: int,
        limit: int = 5,
    ) -> dict[str, Any]:
        bounded_limit = min(max(int(limit or 5), 1), 20)
        actions = (
            await session.exec(
                select(OptimizationAction)
                .where(
                    and_(
                        OptimizationAction.org_id == org_id,
                        OptimizationAction.status == "applied",
                    )
                )
                .order_by(OptimizationAction.applied_at.desc(), OptimizationAction.id.desc())
                .limit(bounded_limit)
            )
        ).all()

        if not actions:
            return {
                "generated_at": datetime.utcnow(),
                "items": [],
                "totals": {
                    "measured_count": 0,
                    "pending_count": 0,
                    "positive_count": 0,
                },
            }

        action_ids = [row.id for row in actions if row.id is not None]
        site_ids = [row.site_id for row in actions if row.site_id is not None]

        arm_rows = []
        if action_ids:
            arm_rows = (
                await session.exec(
                    select(OptimizationBanditArm).where(
                        and_(
                            OptimizationBanditArm.org_id == org_id,
                            OptimizationBanditArm.action_id.in_(action_ids),
                        )
                    )
                )
            ).all()
        site_rows = []
        if site_ids:
            site_rows = (
                await session.exec(select(Site).where(Site.id.in_(site_ids)))
            ).all()
        site_by_id = {row.id: row for row in site_rows if row.id is not None}
        arm_by_action_id = {row.action_id: row for row in arm_rows}

        measured_count = 0
        pending_count = 0
        positive_count = 0
        items: list[dict[str, Any]] = []

        for action in actions:
            action_id = action.id
            arm = arm_by_action_id.get(action_id) if action_id is not None else None
            arm_meta = self._parse_json_dict(arm.metadata_json if arm else None)
            auto_eval = arm_meta.get("auto_eval", {}) if isinstance(arm_meta.get("auto_eval"), dict) else {}

            has_measured_eval = auto_eval.get("post_snapshot_id") is not None and auto_eval.get("baseline_snapshot_id") is not None
            site = site_by_id.get(action.site_id)
            site_label = site.url if site else f"Site #{action.site_id}"

            if has_measured_eval:
                baseline_score = round(float(auto_eval.get("baseline_proof_score", 0.0)), 1)
                post_score = round(float(auto_eval.get("post_proof_score", 0.0)), 1)
                delta_score = round(float(auto_eval.get("delta_proof_score", post_score - baseline_score)), 1)
                reward = round(float(auto_eval.get("reward", arm.last_reward if arm else 0.0)), 3)
                delta_prefix = "+" if delta_score >= 0 else ""
                narrative = (
                    f"{site_label}에서 '{action.title}' 적용 후 Proof Score가 "
                    f"{baseline_score} -> {post_score} ({delta_prefix}{delta_score})로 변했습니다."
                )
                if delta_score > 0:
                    positive_count += 1
                measured_count += 1
                items.append(
                    {
                        "action_id": action.id,
                        "site_id": action.site_id,
                        "site_label": site_label,
                        "title": action.title,
                        "applied_at": action.applied_at,
                        "evidence_type": "measured",
                        "status": "measured",
                        "baseline_proof_score": baseline_score,
                        "post_proof_score": post_score,
                        "delta_proof_score": delta_score,
                        "reward": reward,
                        "confidence_level": auto_eval.get("post_confidence_level", "low"),
                        "narrative": narrative,
                    }
                )
            else:
                pending_count += 1
                items.append(
                    {
                        "action_id": action.id,
                        "site_id": action.site_id,
                        "site_label": site_label,
                        "title": action.title,
                        "applied_at": action.applied_at,
                        "evidence_type": "predicted",
                        "status": "pending_measurement",
                        "reward": None,
                        "confidence_level": None,
                        "narrative": (
                            f"{site_label}에서 '{action.title}'를 적용했습니다. "
                            "다음 Proof Snapshot 생성 후 측정값이 자동으로 채워집니다."
                        ),
                    }
                )

        return {
            "generated_at": datetime.utcnow(),
            "items": items,
            "totals": {
                "measured_count": measured_count,
                "pending_count": pending_count,
                "positive_count": positive_count,
            },
        }


optimization_service = OptimizationService()
