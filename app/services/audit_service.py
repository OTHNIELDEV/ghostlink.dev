import json
import logging
from typing import Any, Optional

from sqlalchemy import text
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.engine import async_session_factory
from app.models.audit_log import AuditLog


logger = logging.getLogger(__name__)


class AuditService:
    async def _insert_event_row(
        self,
        org_id: int,
        action: str,
        actor_user_id: Optional[int],
        resource_type: Optional[str],
        resource_id: Optional[str],
        metadata_json: str,
    ) -> AuditLog:
        async with async_session_factory() as audit_session:
            row = AuditLog(
                org_id=org_id,
                actor_user_id=actor_user_id,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                metadata_json=metadata_json,
            )
            audit_session.add(row)
            await audit_session.commit()
            await audit_session.refresh(row)
            return row

    async def _repair_auditlog_sequence_if_needed(self) -> bool:
        async with async_session_factory() as audit_session:
            bind = audit_session.get_bind()
            if not bind or bind.dialect.name != "postgresql":
                return False

            await audit_session.execute(
                text(
                    "SELECT setval("
                    "pg_get_serial_sequence('auditlog', 'id'), "
                    "COALESCE((SELECT MAX(id) FROM auditlog), 0) + 1, "
                    "false)"
                )
            )
            await audit_session.commit()
            return True

    def _is_auditlog_pk_conflict(self, exc: Exception) -> bool:
        message = str(exc).lower()
        return "auditlog_pkey" in message and "duplicate key value violates unique constraint" in message

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
        metadata_json = json.dumps(metadata or {}, ensure_ascii=True)

        # Keep compatibility for callers that intentionally stage audit rows
        # in the current transaction.
        if not commit:
            row = AuditLog(
                org_id=org_id,
                actor_user_id=actor_user_id,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                metadata_json=metadata_json,
            )
            session.add(row)
            return row

        try:
            return await self._insert_event_row(
                org_id=org_id,
                action=action,
                actor_user_id=actor_user_id,
                resource_type=resource_type,
                resource_id=resource_id,
                metadata_json=metadata_json,
            )
        except Exception as exc:
            if self._is_auditlog_pk_conflict(exc):
                logger.warning(
                    "Audit log PK conflict detected for action=%s org_id=%s; attempting sequence repair.",
                    action,
                    org_id,
                )
                try:
                    repaired = await self._repair_auditlog_sequence_if_needed()
                    if repaired:
                        return await self._insert_event_row(
                            org_id=org_id,
                            action=action,
                            actor_user_id=actor_user_id,
                            resource_type=resource_type,
                            resource_id=resource_id,
                            metadata_json=metadata_json,
                        )
                except Exception as retry_exc:
                    logger.warning(
                        "Audit log retry failed after sequence repair for action=%s org_id=%s: %s",
                        action,
                        org_id,
                        retry_exc,
                    )

            logger.warning("Audit log write failed for action=%s org_id=%s: %s", action, org_id, exc)
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
