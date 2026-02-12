import asyncio

import pytest

from app.services.audit_service import AuditService


class _CallerSession:
    def __init__(self):
        self.add_called = False
        self.rollback_called = False

    def add(self, _row):
        self.add_called = True

    async def rollback(self):
        self.rollback_called = True


def test_log_event_commit_false_stages_row_in_caller_session():
    service = AuditService()
    session = _CallerSession()

    row = asyncio.run(
        service.log_event(
            session=session,
            org_id=1,
            action="test.action",
            actor_user_id=1,
            commit=False,
        )
    )

    assert row is not None
    assert session.add_called is True


def test_log_event_commit_true_does_not_rollback_caller_session_on_insert_failure(
    monkeypatch: pytest.MonkeyPatch,
):
    service = AuditService()
    session = _CallerSession()

    async def _raise_duplicate(*_args, **_kwargs):
        raise RuntimeError('duplicate key value violates unique constraint "auditlog_pkey"')

    async def _no_repair():
        return False

    monkeypatch.setattr(service, "_insert_event_row", _raise_duplicate)
    monkeypatch.setattr(service, "_repair_auditlog_sequence_if_needed", _no_repair)

    row = asyncio.run(
        service.log_event(
            session=session,
            org_id=1,
            action="test.action",
            actor_user_id=1,
            commit=True,
        )
    )

    assert row is None
    assert session.add_called is False
    assert session.rollback_called is False


def test_log_event_retries_after_sequence_repair(monkeypatch: pytest.MonkeyPatch):
    service = AuditService()
    session = _CallerSession()
    calls = {"count": 0}

    async def _insert_with_retry(*_args, **_kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError('duplicate key value violates unique constraint "auditlog_pkey"')
        return object()

    async def _repair_ok():
        return True

    monkeypatch.setattr(service, "_insert_event_row", _insert_with_retry)
    monkeypatch.setattr(service, "_repair_auditlog_sequence_if_needed", _repair_ok)

    row = asyncio.run(
        service.log_event(
            session=session,
            org_id=1,
            action="test.action",
            actor_user_id=1,
            commit=True,
        )
    )

    assert row is not None
    assert calls["count"] == 2
