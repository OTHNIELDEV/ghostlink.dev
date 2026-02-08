from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlmodel import and_, func, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.analytics import BotVisit, BridgeEvent
from app.models.innovation import (
    AnswerCaptureQuerySet,
    AnswerCaptureRun,
    OnboardingProgress,
)
from app.models.site import Site


class OnboardingService:
    STEPS: list[dict[str, str]] = [
        {
            "key": "add_site",
            "title": "Add Your First Site",
            "description": "Register at least one website in GhostLink.",
            "action_label": "Add Site",
        },
        {
            "key": "first_scan_completed",
            "title": "Complete First Scan",
            "description": "Finish one AI scan and generate score + assets.",
            "action_label": "View Dashboard",
        },
        {
            "key": "install_bridge_script",
            "title": "Install Bridge Script",
            "description": "Apply GhostLink script to your production website.",
            "action_label": "Open Install Guide",
        },
        {
            "key": "create_query_set",
            "title": "Create Question Set",
            "description": "Define key AI search questions for your brand.",
            "action_label": "Open Proof Center",
        },
        {
            "key": "run_first_proof",
            "title": "Run First Proof",
            "description": "Collect measurable ACR/Citation proof from answers.",
            "action_label": "Run Proof",
        },
    ]

    def _build_action_url(self, step_key: str, org_id: int, primary_site_id: int | None) -> str:
        if step_key == "add_site":
            return f"/dashboard?org_id={org_id}"
        if step_key == "first_scan_completed":
            return f"/dashboard?org_id={org_id}"
        if step_key == "install_bridge_script":
            if primary_site_id:
                return f"/report/{primary_site_id}?org_id={org_id}#integration-guide"
            return f"/dashboard?org_id={org_id}"
        if step_key == "create_query_set":
            return f"/proof?org_id={org_id}#query-set"
        if step_key == "run_first_proof":
            return f"/proof?org_id={org_id}#run-proof"
        return f"/dashboard?org_id={org_id}"

    async def get_status(
        self,
        session: AsyncSession,
        org_id: int,
        user_id: int | None = None,
    ) -> dict[str, Any]:
        sites = (
            await session.exec(
                select(Site).where(Site.org_id == org_id).order_by(Site.created_at.asc())
            )
        ).all()
        site_ids = [row.id for row in sites if row.id is not None]
        primary_site_id = site_ids[0] if site_ids else None

        site_count = len(site_ids)
        scanned_count = len(
            [
                row
                for row in sites
                if row.status in {"active", "completed"}
            ]
        )

        script_requests = 0
        bridge_events = 0
        if site_ids:
            script_requests = int(
                (
                    await session.exec(
                        select(func.count())
                        .select_from(BotVisit)
                        .where(BotVisit.site_id.in_(site_ids))
                    )
                ).one()
                or 0
            )
            bridge_events = int(
                (
                    await session.exec(
                        select(func.count())
                        .select_from(BridgeEvent)
                        .where(BridgeEvent.site_id.in_(site_ids))
                    )
                ).one()
                or 0
            )

        query_set_count = int(
            (
                await session.exec(
                    select(func.count())
                    .select_from(AnswerCaptureQuerySet)
                    .where(AnswerCaptureQuerySet.org_id == org_id)
                )
            ).one()
            or 0
        )
        proof_run_count = int(
            (
                await session.exec(
                    select(func.count())
                    .select_from(AnswerCaptureRun)
                    .where(
                        and_(
                            AnswerCaptureRun.org_id == org_id,
                            AnswerCaptureRun.status == "completed",
                        )
                    )
                )
            ).one()
            or 0
        )

        progress_rows = (
            await session.exec(
                select(OnboardingProgress).where(OnboardingProgress.org_id == org_id)
            )
        ).all()
        manual_completed_keys = {
            str(row.step_key)
            for row in progress_rows
            if str(row.status).strip().lower() == "completed"
        }

        auto_completed = {
            "add_site": site_count > 0,
            "first_scan_completed": scanned_count > 0,
            "install_bridge_script": (script_requests + bridge_events) > 0,
            "create_query_set": query_set_count > 0,
            "run_first_proof": proof_run_count > 0,
        }

        steps: list[dict[str, Any]] = []
        completed_count = 0
        next_step: dict[str, Any] | None = None
        for step in self.STEPS:
            key = step["key"]
            is_manual_done = key in manual_completed_keys
            is_auto_done = bool(auto_completed.get(key, False))
            is_completed = is_manual_done or is_auto_done
            if is_completed:
                completed_count += 1

            item = {
                "key": key,
                "title": step["title"],
                "description": step["description"],
                "status": "completed" if is_completed else "pending",
                "is_auto_completed": is_auto_done,
                "is_manual_completed": is_manual_done,
                "action_label": step["action_label"],
                "action_url": self._build_action_url(key, org_id, primary_site_id),
            }
            steps.append(item)
            if next_step is None and not is_completed:
                next_step = item

        total_steps = len(self.STEPS)
        progress_pct = round((completed_count / total_steps) * 100) if total_steps else 0

        return {
            "org_id": org_id,
            "user_id": user_id,
            "progress_pct": progress_pct,
            "completed_count": completed_count,
            "total_steps": total_steps,
            "is_completed": completed_count >= total_steps and total_steps > 0,
            "next_step": next_step,
            "steps": steps,
            "signals": {
                "site_count": site_count,
                "scanned_site_count": scanned_count,
                "script_request_count": script_requests,
                "bridge_event_count": bridge_events,
                "query_set_count": query_set_count,
                "proof_run_count": proof_run_count,
            },
        }

    async def complete_step(
        self,
        session: AsyncSession,
        org_id: int,
        user_id: int,
        step_key: str,
    ) -> OnboardingProgress:
        valid_step_keys = {row["key"] for row in self.STEPS}
        key = (step_key or "").strip()
        if key not in valid_step_keys:
            raise ValueError("Invalid onboarding step key")

        row = (
            await session.exec(
                select(OnboardingProgress).where(
                    and_(
                        OnboardingProgress.org_id == org_id,
                        OnboardingProgress.step_key == key,
                    )
                )
            )
        ).first()

        now = datetime.utcnow()
        if row:
            row.status = "completed"
            row.completed_by_user_id = user_id
            row.completed_at = now
            row.updated_at = now
        else:
            row = OnboardingProgress(
                org_id=org_id,
                step_key=key,
                status="completed",
                completed_by_user_id=user_id,
                completed_at=now,
                updated_at=now,
            )

        session.add(row)
        await session.commit()
        await session.refresh(row)
        return row


onboarding_service = OnboardingService()
