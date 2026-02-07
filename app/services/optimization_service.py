import json
from datetime import datetime

from sqlmodel import and_, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.optimization import OptimizationAction
from app.models.site import Site


class OptimizationService:
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


optimization_service = OptimizationService()
