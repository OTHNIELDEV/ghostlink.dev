import asyncio
from datetime import datetime, timedelta

from fastapi.testclient import TestClient
from sqlmodel import select

from app.db.engine import get_session
from app.main import app
from app.models.analytics import BotVisit, BridgeEvent, BridgeEventRaw
from app.models.site import Site
from app.routers.bridge import BRIDGE_RAW_MAX_RETRIES, _build_bridge_token, process_bridge_raw_queue_background


async def _create_site(url: str) -> Site:
    async for session in get_session():
        site = Site(
            url=url,
            status="completed",
            ai_score=75,
            schema_type="WebSite",
            updated_at=datetime.utcnow(),
        )
        session.add(site)
        await session.commit()
        await session.refresh(site)
        return site


async def _bridge_event_count(site_id: int) -> int:
    async for session in get_session():
        rows = (await session.exec(select(BridgeEvent).where(BridgeEvent.site_id == site_id))).all()
        return len(rows)
    return 0


async def _bridge_event_types(site_id: int) -> list[str]:
    async for session in get_session():
        rows = (
            await session.exec(
                select(BridgeEvent.event_type).where(BridgeEvent.site_id == site_id).order_by(BridgeEvent.id.asc())
            )
        ).all()
        return [str(row) for row in rows]
    return []


async def _raw_event_stats(site_id: int) -> dict[str, int]:
    async for session in get_session():
        rows = (
            await session.exec(
                select(BridgeEventRaw).where(BridgeEventRaw.site_id == site_id).order_by(BridgeEventRaw.id.asc())
            )
        ).all()
        total = len(rows)
        dropped = len([row for row in rows if row.dropped_reason])
        normalized = len([row for row in rows if row.normalized and not row.dropped_reason])
        return {
            "total": total,
            "dropped": dropped,
            "normalized": normalized,
        }
    return {"total": 0, "dropped": 0, "normalized": 0}


async def _insert_raw_event(site_id: int, payload_json: str, event_id: str) -> int:
    async for session in get_session():
        row = BridgeEventRaw(
            site_id=site_id,
            event_id=event_id,
            ingest_source="batch_post",
            event_type="pageview",
            payload_json=payload_json,
            normalized=False,
            dropped_reason=None,
            retry_count=0,
            request_user_agent="pytest-agent",
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return int(row.id)
    return 0


async def _get_raw_event(row_id: int) -> BridgeEventRaw | None:
    async for session in get_session():
        return await session.get(BridgeEventRaw, row_id)
    return None


async def _force_retry_due(row_id: int) -> None:
    async for session in get_session():
        row = await session.get(BridgeEventRaw, row_id)
        if row is None:
            return
        row.next_retry_at = datetime.utcnow() - timedelta(seconds=1)
        session.add(row)
        await session.commit()
        return


async def _cleanup_site(site_id: int) -> None:
    async for session in get_session():
        bridge_events = (await session.exec(select(BridgeEvent).where(BridgeEvent.site_id == site_id))).all()
        for row in bridge_events:
            await session.delete(row)

        raw_rows = (await session.exec(select(BridgeEventRaw).where(BridgeEventRaw.site_id == site_id))).all()
        for row in raw_rows:
            await session.delete(row)

        bot_visits = (await session.exec(select(BotVisit).where(BotVisit.site_id == site_id))).all()
        for row in bot_visits:
            await session.delete(row)

        site = await session.get(Site, site_id)
        if site:
            await session.delete(site)

        await session.commit()
        break


def _token_payload(script_id: str) -> dict[str, str]:
    exp, nonce, sig = _build_bridge_token(script_id)
    return {
        "gx": str(exp),
        "gn": nonce,
        "gs": sig,
    }


def test_bridge_script_includes_batch_ingest_logic():
    site = asyncio.run(_create_site("https://bridge-script-test.example"))
    try:
        with TestClient(app) as client:
            response = client.get(
                f"/api/bridge/{site.script_id}.js",
                headers={"user-agent": "Mozilla/5.0 (Pytest Browser)"},
            )
            assert response.status_code == 200
            assert "const batchEndpoint =" in response.text
            assert "sendBatchWithBeacon" in response.text
            assert "MAX_BATCH_SIZE" in response.text
            assert "enqueueEvent('pageview')" in response.text
    finally:
        asyncio.run(_cleanup_site(site.id))


def test_bridge_batch_events_ingest_persists_rows():
    site = asyncio.run(_create_site("https://bridge-batch-success.example"))
    try:
        payload = {
            "events": [
                {
                    "event_id": "evt-1",
                    "event_type": "pageview",
                    "session_id": "session-1",
                    "page_url": "/pricing",
                    "page_title": "Pricing",
                },
                {
                    "event_id": "evt-2",
                    "event_type": "engaged_15s",
                    "session_id": "session-1",
                    "page_url": "/pricing",
                    "page_title": "Pricing",
                },
            ],
            **_token_payload(site.script_id),
        }

        with TestClient(app) as client:
            response = client.post(
                f"/api/bridge/{site.script_id}/events",
                json=payload,
                headers={
                    "origin": "https://bridge-batch-success.example",
                    "user-agent": "Mozilla/5.0 (Pytest Browser)",
                },
            )
            assert response.status_code == 200
            body = response.json()
            assert body["accepted"] == 2
            assert body["dropped"] == 0
            assert body["reasons"] == {}

        assert asyncio.run(_bridge_event_count(site.id)) == 2
        event_types = asyncio.run(_bridge_event_types(site.id))
        assert event_types == ["pageview", "engaged_15s"]
        raw_stats = asyncio.run(_raw_event_stats(site.id))
        assert raw_stats["total"] == 2
        assert raw_stats["dropped"] == 0
        assert raw_stats["normalized"] == 2
    finally:
        asyncio.run(_cleanup_site(site.id))


def test_bridge_batch_events_reject_invalid_token():
    site = asyncio.run(_create_site("https://bridge-batch-auth.example"))
    try:
        payload = {
            "events": [
                {
                    "event_id": "evt-invalid",
                    "event_type": "pageview",
                    "session_id": "session-invalid",
                }
            ],
            "gx": "0",
            "gn": "invalid",
            "gs": "invalid",
        }

        with TestClient(app) as client:
            response = client.post(
                f"/api/bridge/{site.script_id}/events",
                json=payload,
                headers={
                    "origin": "https://bridge-batch-auth.example",
                    "user-agent": "Mozilla/5.0 (Pytest Browser)",
                },
            )
            assert response.status_code == 403

        assert asyncio.run(_bridge_event_count(site.id)) == 0
    finally:
        asyncio.run(_cleanup_site(site.id))


def test_bridge_batch_events_records_dropped_duplicates():
    site = asyncio.run(_create_site("https://bridge-batch-duplicates.example"))
    try:
        payload = {
            "events": [
                {
                    "event_id": "dup-1",
                    "event_type": "pageview",
                    "session_id": "session-dup",
                },
                {
                    "event_id": "dup-1",
                    "event_type": "engaged_15s",
                    "session_id": "session-dup",
                },
            ],
            **_token_payload(site.script_id),
        }

        with TestClient(app) as client:
            response = client.post(
                f"/api/bridge/{site.script_id}/events",
                json=payload,
                headers={
                    "origin": "https://bridge-batch-duplicates.example",
                    "user-agent": "Mozilla/5.0 (Pytest Browser)",
                },
            )
            assert response.status_code == 200
            body = response.json()
            assert body["accepted"] == 1
            assert body["dropped"] == 1
            assert body["reasons"]["duplicate_event_id"] == 1

        assert asyncio.run(_bridge_event_count(site.id)) == 1
        raw_stats = asyncio.run(_raw_event_stats(site.id))
        assert raw_stats["total"] == 2
        assert raw_stats["dropped"] == 1
        assert raw_stats["normalized"] == 1
    finally:
        asyncio.run(_cleanup_site(site.id))


def test_bridge_token_endpoint_returns_refresh_payload():
    site = asyncio.run(_create_site("https://bridge-token-test.example"))
    try:
        with TestClient(app) as client:
            response = client.get(
                f"/api/bridge/{site.script_id}/token",
                headers={"origin": "https://bridge-token-test.example"},
            )
            assert response.status_code == 200
            body = response.json()
            assert int(body["gx"]) > 0
            assert body["gn"]
            assert body["gs"]
            assert body["ttl_seconds"] > 0
            assert "expires_at" in body
    finally:
        asyncio.run(_cleanup_site(site.id))


def test_bridge_raw_worker_retries_and_marks_retry_exhausted(monkeypatch):
    site = asyncio.run(_create_site("https://bridge-retry-worker.example"))
    try:
        raw_id = asyncio.run(
            _insert_raw_event(
                site.id,
                payload_json=(
                    '{"event_id":"retry-1","event_type":"pageview","session_id":"s1","page_url":"/retry"}'
                ),
                event_id="retry-1",
            )
        )

        def _raise_on_normalize(_: str | None) -> str:
            raise RuntimeError("forced-normalize-error")

        monkeypatch.setattr("app.routers.bridge._normalize_event_type", _raise_on_normalize)

        for attempt in range(BRIDGE_RAW_MAX_RETRIES):
            if attempt > 0:
                asyncio.run(_force_retry_due(raw_id))
            asyncio.run(process_bridge_raw_queue_background(site.id, limit=10))

        row = asyncio.run(_get_raw_event(raw_id))
        assert row is not None
        assert row.normalized is True
        assert row.dropped_reason == "retry_exhausted"
        assert row.retry_count == BRIDGE_RAW_MAX_RETRIES
        assert row.next_retry_at is None
        assert row.last_error is not None
        assert "forced-normalize-error" in row.last_error
        assert asyncio.run(_bridge_event_count(site.id)) == 0
    finally:
        asyncio.run(_cleanup_site(site.id))
