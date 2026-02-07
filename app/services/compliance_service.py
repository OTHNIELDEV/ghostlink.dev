import json
from typing import Any, Optional

from sqlmodel import and_, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.innovation_plus import ComplianceCheckRun, CompliancePolicy
from app.models.site import Site


class ComplianceService:
    def parse_rules(self, raw: str | None) -> dict[str, Any]:
        if not raw:
            return {}
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}

    def parse_violations(self, raw: str | None) -> list[dict[str, Any]]:
        if not raw:
            return []
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, list) else []
        except Exception:
            return []

    async def list_policies(
        self,
        session: AsyncSession,
        org_id: int,
        active_only: bool = False,
    ) -> list[CompliancePolicy]:
        query = select(CompliancePolicy).where(CompliancePolicy.org_id == org_id)
        if active_only:
            query = query.where(CompliancePolicy.is_active == True)  # noqa: E712
        query = query.order_by(CompliancePolicy.created_at.desc())
        rows = await session.exec(query)
        return rows.all()

    async def create_policy(
        self,
        session: AsyncSession,
        org_id: int,
        user_id: int,
        name: str,
        rules: dict[str, Any],
        enforcement_mode: str = "advisory",
        target_scope: str = "site_content",
    ) -> CompliancePolicy:
        policy_name = (name or "").strip()
        if not policy_name:
            raise ValueError("name is required")

        mode = (enforcement_mode or "advisory").strip().lower()
        if mode not in {"advisory", "blocking"}:
            raise ValueError("enforcement_mode must be advisory or blocking")

        row = CompliancePolicy(
            org_id=org_id,
            created_by_user_id=user_id,
            name=policy_name,
            version=1,
            enforcement_mode=mode,
            target_scope=(target_scope or "site_content").strip().lower(),
            rules_json=json.dumps(rules or {}, ensure_ascii=True),
            is_active=True,
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return row

    def evaluate_text(self, text: str, rules: dict[str, Any]) -> list[dict[str, Any]]:
        value = (text or "").strip()
        lowered = value.lower()
        violations: list[dict[str, Any]] = []

        banned_phrases = [str(x).strip() for x in rules.get("banned_phrases", []) if str(x).strip()]
        required_phrases = [str(x).strip() for x in rules.get("required_phrases", []) if str(x).strip()]
        min_length = int(rules.get("min_length", 0) or 0)
        max_length = int(rules.get("max_length", 0) or 0)

        for phrase in banned_phrases:
            if phrase.lower() in lowered:
                violations.append(
                    {
                        "type": "banned_phrase",
                        "severity": "high",
                        "message": f"Banned phrase detected: {phrase}",
                    }
                )

        for phrase in required_phrases:
            if phrase.lower() not in lowered:
                violations.append(
                    {
                        "type": "required_phrase_missing",
                        "severity": "medium",
                        "message": f"Required phrase missing: {phrase}",
                    }
                )

        if min_length > 0 and len(value) < min_length:
            violations.append(
                {
                    "type": "min_length",
                    "severity": "low",
                    "message": f"Text shorter than min_length ({min_length})",
                }
            )
        if max_length > 0 and len(value) > max_length:
            violations.append(
                {
                    "type": "max_length",
                    "severity": "low",
                    "message": f"Text exceeds max_length ({max_length})",
                }
            )

        return violations

    def _compose_site_text(self, site: Site) -> str:
        parts = [
            site.url or "",
            site.meta_description or site.seo_description or "",
            site.llms_txt or site.llms_txt_content or "",
            site.json_ld or site.json_ld_content or "",
            site.custom_instruction or "",
        ]
        return "\n\n".join(part for part in parts if part)

    async def run_policy_for_site(
        self,
        session: AsyncSession,
        org_id: int,
        policy: CompliancePolicy,
        site: Site,
        checked_by_user_id: Optional[int],
    ) -> ComplianceCheckRun:
        text = self._compose_site_text(site)
        rules = self.parse_rules(policy.rules_json)
        violations = self.evaluate_text(text, rules)
        status = "passed" if not violations else "failed"
        summary = {
            "policy_id": policy.id,
            "site_id": site.id,
            "violation_count": len(violations),
            "enforcement_mode": policy.enforcement_mode,
        }

        row = ComplianceCheckRun(
            org_id=org_id,
            policy_id=policy.id,
            site_id=site.id,
            checked_by_user_id=checked_by_user_id,
            target_type="site",
            target_ref=str(site.id),
            status=status,
            summary_json=json.dumps(summary, ensure_ascii=True),
            violations_json=json.dumps(violations, ensure_ascii=True),
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return row

    async def list_site_checks(
        self,
        session: AsyncSession,
        org_id: int,
        site_id: int,
        limit: int = 50,
    ) -> list[ComplianceCheckRun]:
        bounded_limit = min(max(limit, 1), 200)
        rows = await session.exec(
            select(ComplianceCheckRun)
            .where(
                and_(
                    ComplianceCheckRun.org_id == org_id,
                    ComplianceCheckRun.site_id == site_id,
                )
            )
            .order_by(ComplianceCheckRun.created_at.desc())
            .limit(bounded_limit)
        )
        return rows.all()

    async def evaluate_text_against_active_policies(
        self,
        session: AsyncSession,
        org_id: int,
        text: str,
        blocking_only: bool = True,
    ) -> dict[str, Any]:
        policies = await self.list_policies(session, org_id, active_only=True)
        if blocking_only:
            policies = [policy for policy in policies if policy.enforcement_mode == "blocking"]

        results = []
        total_violations = 0
        for policy in policies:
            rules = self.parse_rules(policy.rules_json)
            violations = self.evaluate_text(text, rules)
            total_violations += len(violations)
            results.append(
                {
                    "policy_id": policy.id,
                    "policy_name": policy.name,
                    "enforcement_mode": policy.enforcement_mode,
                    "violations": violations,
                }
            )

        return {
            "policy_count": len(policies),
            "total_violations": total_violations,
            "results": results,
        }

    async def get_policy(self, session: AsyncSession, org_id: int, policy_id: int) -> Optional[CompliancePolicy]:
        row = await session.exec(
            select(CompliancePolicy).where(
                and_(
                    CompliancePolicy.org_id == org_id,
                    CompliancePolicy.id == policy_id,
                )
            )
        )
        return row.first()

    async def get_site(self, session: AsyncSession, org_id: int, site_id: int) -> Optional[Site]:
        row = await session.exec(
            select(Site).where(
                and_(
                    Site.org_id == org_id,
                    Site.id == site_id,
                )
            )
        )
        return row.first()


compliance_service = ComplianceService()
