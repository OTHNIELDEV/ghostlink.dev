import json
import logging
from typing import Any, Optional

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.audit_log import AuditLog


logger = logging.getLogger(__name__)


class AuditService:
    async def log_event(
        self,
        session: AsyncSession,
        org_id: int,
        action: str,
        actor_user_id: Optional[int] = None,
        resource_type: Optional[str] = None,
        resource_id: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
        commit: bool = True,
    ) -> Optional[AuditLog]:
        try:
            row = AuditLog(
                org_id=org_id,
                actor_user_id=actor_user_id,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                metadata_json=json.dumps(metadata or {}, ensure_ascii=True),
            )
            session.add(row)
            if commit:
                await session.commit()
                await session.refresh(row)
            return row
        except Exception as exc:
            logger.warning("Audit log write failed for action=%s org_id=%s: %s", action, org_id, exc)
            try:
                await session.rollback()
            except Exception:
                pass
            return None

    async def list_logs(
        self,
        session: AsyncSession,
        org_id: int,
        limit: int = 50,
        action: Optional[str] = None,
    ) -> list[AuditLog]:
        bounded_limit = min(max(limit, 1), 200)
        query = select(AuditLog).where(AuditLog.org_id == org_id)
        if action:
            query = query.where(AuditLog.action == action)
        query = query.order_by(AuditLog.created_at.desc()).limit(bounded_limit)
        result = await session.exec(query)
        return result.all()

    def parse_metadata(self, row: AuditLog) -> dict[str, Any]:
        try:
            parsed = json.loads(row.metadata_json or "{}")
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}


audit_service = AuditService()
