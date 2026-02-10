import base64
import hashlib
import hmac
import json
import logging
import secrets
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from fastapi import APIRouter, BackgroundTasks, Depends, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import and_, or_, select
from app.core.config import settings
from app.db.engine import get_session
from app.models.site import Site
from app.models.analytics import BotVisit, BridgeEvent, BridgeEventRaw
from app.services.edge_service import edge_service

logger = logging.getLogger(__name__)

router = APIRouter()

# Known Bot User-Agents (Simple matching for MVP)
BOT_SIGNATURES = {
    "GPTBot": "GPTBot",
    "ClaudeBot": "ClaudeBot",
    "Google-Extended": "Google-Extended",
    "Applebot": "Applebot",
    "Bingbot": "bingbot",
    "Twitterbot": "Twitterbot",
    "FacebookExternalHit": "facebookexternalhit"
}

# Simple In-Memory Cache
# Key: (script_id, is_bot), Value: (js_content, site_id, cached_at_epoch)
SCRIPT_CACHE = {}
SITE_CACHE = {}  # Key: script_id, Value: (site_id, site_url, cached_at_epoch)
CACHE_TTL = 3600  # 1 hour in seconds
MAX_BRIDGE_BATCH_EVENTS = 100
MAX_CLIENT_QUEUE_SIZE = 200
BRIDGE_RAW_WORKER_BATCH_SIZE = 250
BRIDGE_RAW_MAX_RETRIES = 3
BRIDGE_RAW_RETRY_BASE_SECONDS = 15
BRIDGE_RAW_RETRY_MAX_SECONDS = 300
ALLOWED_BRIDGE_EVENT_TYPES = {
    "pageview",
    "engaged_15s",
    "hidden",
    "leave",
    "heartbeat",
    "route_change",
    "custom",
}


def invalidate_script_cache(script_id: str):
    # Invalidate both bot and human versions
    SCRIPT_CACHE.pop((script_id, True), None)
    SCRIPT_CACHE.pop((script_id, False), None)
    SITE_CACHE.pop(script_id, None)


def _detect_bot(user_agent: str) -> str:
    detected_bot = "Human/Browser"
    for bot_key, signature in BOT_SIGNATURES.items():
        if signature.lower() in user_agent.lower():
            detected_bot = bot_key
            break
    return detected_bot


def _clip(value: str | None, max_len: int = 255) -> str | None:
    if not value:
        return None
    return value[:max_len]


def _bridge_secret() -> bytes:
    secret = settings.BRIDGE_SIGNING_SECRET or settings.SECRET_KEY
    return secret.encode("utf-8")


def _b64(value: str) -> str:
    return base64.b64encode(value.encode("utf-8")).decode("ascii")


def _sign_bridge_token(script_id: str, exp: int, nonce: str) -> str:
    payload = f"{script_id}:{exp}:{nonce}"
    return hmac.new(_bridge_secret(), payload.encode("utf-8"), hashlib.sha256).hexdigest()


def _build_bridge_token(script_id: str, now_epoch: int | None = None) -> tuple[int, str, str]:
    now_epoch = now_epoch or int(time.time())
    exp = now_epoch + settings.BRIDGE_EVENT_TOKEN_TTL_SECONDS
    nonce = secrets.token_urlsafe(10)
    sig = _sign_bridge_token(script_id, exp, nonce)
    return exp, nonce, sig


def _verify_bridge_token(script_id: str, exp_raw: str | None, nonce: str | None, sig: str | None) -> bool:
    if not exp_raw or not nonce or not sig:
        return False
    try:
        exp = int(exp_raw)
    except ValueError:
        return False
    if exp < int(time.time()):
        return False
    expected = _sign_bridge_token(script_id, exp, nonce)
    return hmac.compare_digest(expected, sig)


def _normalize_host(raw_url: str | None) -> str | None:
    if not raw_url:
        return None
    parsed = urlparse(raw_url)
    host = (parsed.hostname or "").lower().strip()
    if host.startswith("www."):
        host = host[4:]
    return host or None


def _is_allowed_host(source_host: str | None, site_host: str | None) -> bool:
    if not source_host or not site_host:
        return False
    return (
        source_host == site_host
        or source_host.endswith(f".{site_host}")
        or site_host.endswith(f".{source_host}")
    )


def _validate_event_origin(request: Request, site_url: str) -> bool:
    site_host = _normalize_host(site_url)
    if not site_host:
        return True

    referer_host = _normalize_host(request.headers.get("referer"))
    if referer_host:
        return _is_allowed_host(referer_host, site_host)

    origin_host = _normalize_host(request.headers.get("origin"))
    if origin_host:
        return _is_allowed_host(origin_host, site_host)

    # Some deployments strip referer/origin. Keep collection working but rely on token validation.
    return True


class BridgeBatchEvent(BaseModel):
    event_id: str | None = Field(default=None, max_length=128)
    event_type: str = Field(default="pageview", min_length=1, max_length=64)
    session_id: str | None = Field(default=None, max_length=128)
    page_url: str | None = Field(default=None, max_length=1024)
    page_title: str | None = Field(default=None, max_length=512)
    referrer: str | None = Field(default=None, max_length=1024)
    language: str | None = Field(default=None, max_length=32)
    timezone: str | None = Field(default=None, max_length=64)
    viewport: str | None = Field(default=None, max_length=32)
    occurred_at: str | None = Field(default=None, max_length=64)


class BridgeBatchRequest(BaseModel):
    events: list[BridgeBatchEvent] = Field(default_factory=list)
    gx: str = Field(min_length=1, max_length=32)
    gn: str = Field(min_length=1, max_length=64)
    gs: str = Field(min_length=1, max_length=128)
    sent_at: str | None = Field(default=None, max_length=64)


def _normalize_event_type(raw_event_type: str | None) -> str:
    event_type = (raw_event_type or "pageview").strip().lower()
    if event_type not in ALLOWED_BRIDGE_EVENT_TYPES:
        return "custom"
    return event_type


def _bridge_event_payload_from_query(query_params: dict[str, str]) -> dict[str, str | None]:
    return {
        "event_id": None,
        "event_type": _normalize_event_type(query_params.get("e")),
        "session_id": _clip(query_params.get("sid"), 128),
        "page_url": _clip(query_params.get("p"), 1024),
        "page_title": _clip(query_params.get("t"), 512),
        "referrer": _clip(query_params.get("r"), 1024),
        "language": _clip(query_params.get("lang"), 32),
        "timezone": _clip(query_params.get("tz"), 64),
        "viewport": _clip(query_params.get("vp"), 32),
        "occurred_at": None,
    }


def _bridge_event_payload_from_batch(item: BridgeBatchEvent) -> dict[str, str | None]:
    return {
        "event_id": _clip(item.event_id, 128),
        "event_type": _normalize_event_type(item.event_type),
        "session_id": _clip(item.session_id, 128),
        "page_url": _clip(item.page_url, 1024),
        "page_title": _clip(item.page_title, 512),
        "referrer": _clip(item.referrer, 1024),
        "language": _clip(item.language, 32),
        "timezone": _clip(item.timezone, 64),
        "viewport": _clip(item.viewport, 32),
        "occurred_at": _clip(item.occurred_at, 64),
    }


def _parse_occurred_at(raw: str | None) -> datetime | None:
    if raw is None:
        return None
    if not isinstance(raw, str):
        return None
    value = raw.strip()
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _build_bridge_script(site: Site, is_bot: bool, script_host: str) -> str:
    """
    Builds the JS script.
    - If Bot: Injects the full JSON-LD.
    - If Human: Runs lightweight analytics events for better visibility.
    """
    if not is_bot:
        analytics_endpoint = f"{script_host}/api/bridge/{site.script_id}/event"
        batch_endpoint = f"{script_host}/api/bridge/{site.script_id}/events"
        token_endpoint = f"{script_host}/api/bridge/{site.script_id}/token"
        token_exp, token_nonce, token_sig = _build_bridge_token(site.script_id)
        endpoint_b64 = _b64(analytics_endpoint)
        batch_endpoint_b64 = _b64(batch_endpoint)
        token_endpoint_b64 = _b64(token_endpoint)
        nonce_b64 = _b64(token_nonce)
        sig_b64 = _b64(token_sig)
        return f"""
/**
 * GhostLink AI Optimization
 * Site: {site.url}
 * Status: Active (Human Analytics + Bot Optimization Ready)
 */
(function() {{
    if (window.__ghostlinkInitialized) return;
    window.__ghostlinkInitialized = true;

    const decode = (v) => atob(v);
    const endpoint = decode({json.dumps(endpoint_b64)});
    const batchEndpoint = decode({json.dumps(batch_endpoint_b64)});
    const tokenEndpoint = decode({json.dumps(token_endpoint_b64)});
    const scriptId = {json.dumps(site.script_id)};
    let tokenExp = {token_exp};
    let tokenNonce = decode({json.dumps(nonce_b64)});
    let tokenSig = decode({json.dumps(sig_b64)});
    const MAX_BATCH_SIZE = 10;
    const MAX_QUEUE_SIZE = {MAX_CLIENT_QUEUE_SIZE};
    const FLUSH_INTERVAL_MS = 4000;
    const TOKEN_REFRESH_BUFFER_SEC = 60;
    const queue = [];
    let flushTimer = null;
    const dntEnabled = navigator.doNotTrack === '1' || window.doNotTrack === '1';

    if (dntEnabled) {{
        console.log('GhostLink: DNT enabled, analytics skipped.');
        return;
    }}

    let sessionId = '';
    try {{
        const key = `gl_sid_${{scriptId}}`;
        sessionId = sessionStorage.getItem(key) || '';
        if (!sessionId) {{
            sessionId = `${{Date.now().toString(36)}}-${{Math.random().toString(36).slice(2, 10)}}`;
            sessionStorage.setItem(key, sessionId);
        }}
    }} catch (_) {{
        sessionId = `${{Date.now().toString(36)}}-${{Math.random().toString(36).slice(2, 10)}}`;
    }}

    function newEventId() {{
        return `${{Date.now().toString(36)}}-${{Math.random().toString(36).slice(2, 10)}}-${{Math.random().toString(36).slice(2, 8)}}`;
    }}

    function buildEvent(eventType) {{
        return {{
            event_id: newEventId(),
            event_type: eventType,
            session_id: sessionId,
            page_url: `${{location.pathname}}${{location.search}}`,
            page_title: document.title || '',
            referrer: document.referrer || '',
            language: navigator.language || '',
            timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || '',
            viewport: `${{window.innerWidth}}x${{window.innerHeight}}`,
            occurred_at: new Date().toISOString()
        }};
    }}

    function sendLegacyEvent(eventType) {{
        try {{
            const params = new URLSearchParams({{
                e: eventType,
                sid: sessionId,
                p: `${{location.pathname}}${{location.search}}`,
                t: document.title || '',
                r: document.referrer || '',
                lang: navigator.language || '',
                tz: Intl.DateTimeFormat().resolvedOptions().timeZone || '',
                vp: `${{window.innerWidth}}x${{window.innerHeight}}`,
                gx: String(tokenExp),
                gn: tokenNonce,
                gs: tokenSig
            }});
            const beacon = new Image();
            beacon.src = `${{endpoint}}?${{params.toString()}}`;
        }} catch (_) {{
            // Non-blocking by design.
        }}
    }}

    async function refreshTokenIfNeeded(force) {{
        const nowSec = Math.floor(Date.now() / 1000);
        if (!force && tokenExp - nowSec > TOKEN_REFRESH_BUFFER_SEC) {{
            return true;
        }}
        try {{
            const response = await fetch(tokenEndpoint, {{
                method: 'GET',
                credentials: 'omit',
                mode: 'cors',
                keepalive: true
            }});
            if (!response.ok) {{
                return false;
            }}
            const data = await response.json();
            if (!data || !data.gx || !data.gn || !data.gs) {{
                return false;
            }}
            tokenExp = Number(data.gx) || tokenExp;
            tokenNonce = String(data.gn);
            tokenSig = String(data.gs);
            return true;
        }} catch (_) {{
            return false;
        }}
    }}

    function sendBatchWithBeacon(events) {{
        if (!navigator.sendBeacon) return false;
        try {{
            const body = JSON.stringify({{
                events: events,
                gx: String(tokenExp),
                gn: tokenNonce,
                gs: tokenSig,
                sent_at: new Date().toISOString()
            }});
            const blob = new Blob([body], {{ type: 'application/json' }});
            return navigator.sendBeacon(batchEndpoint, blob);
        }} catch (_) {{
            return false;
        }}
    }}

    async function sendBatchWithFetch(events) {{
        try {{
            const response = await fetch(batchEndpoint, {{
                method: 'POST',
                headers: {{ 'Content-Type': 'application/json' }},
                body: JSON.stringify({{
                    events: events,
                    gx: String(tokenExp),
                    gn: tokenNonce,
                    gs: tokenSig,
                    sent_at: new Date().toISOString()
                }}),
                keepalive: true,
                credentials: 'omit',
                mode: 'cors'
            }});
            return response.ok;
        }} catch (_) {{
            return false;
        }}
    }}

    function enqueueEvent(eventType) {{
        queue.push(buildEvent(eventType));
        if (queue.length > MAX_QUEUE_SIZE) {{
            queue.splice(0, queue.length - MAX_QUEUE_SIZE);
        }}
        scheduleFlush();
    }}

    function scheduleFlush() {{
        if (flushTimer) return;
        flushTimer = window.setTimeout(() => {{
            flushTimer = null;
            void flushQueue({{ reason: 'interval', useBeacon: false }});
        }}, FLUSH_INTERVAL_MS);
    }}

    async function flushQueue(options) {{
        if (!queue.length) return;

        const useBeacon = Boolean(options && options.useBeacon);
        const reason = (options && options.reason) || 'interval';
        await refreshTokenIfNeeded(false);
        const batch = queue.splice(0, MAX_BATCH_SIZE);

        let ok = false;
        if (useBeacon) {{
            ok = sendBatchWithBeacon(batch);
        }}
        if (!ok) {{
            ok = await sendBatchWithFetch(batch);
        }}

        if (!ok) {{
            queue.unshift(...batch);
            if (queue.length > MAX_QUEUE_SIZE) {{
                queue.splice(0, queue.length - MAX_QUEUE_SIZE);
            }}
            sendLegacyEvent(reason === 'hidden' ? 'hidden' : 'pageview');
            return;
        }}

        if (queue.length && !useBeacon) {{
            scheduleFlush();
        }}
    }}

    enqueueEvent('pageview');
    setTimeout(() => enqueueEvent('engaged_15s'), 15000);

    const originalPushState = history.pushState;
    const originalReplaceState = history.replaceState;

    history.pushState = function(...args) {{
        const result = originalPushState.apply(this, args);
        enqueueEvent('route_change');
        return result;
    }};

    history.replaceState = function(...args) {{
        const result = originalReplaceState.apply(this, args);
        enqueueEvent('route_change');
        return result;
    }};

    window.addEventListener('popstate', () => enqueueEvent('route_change'), {{ passive: true }});

    document.addEventListener('visibilitychange', () => {{
        if (document.visibilityState === 'hidden') {{
            enqueueEvent('hidden');
            void flushQueue({{ reason: 'hidden', useBeacon: true }});
        }}
    }}, {{ passive: true }});

    window.addEventListener('pagehide', () => {{
        enqueueEvent('leave');
        void flushQueue({{ reason: 'leave', useBeacon: true }});
    }}, {{ passive: true }});

    console.log('GhostLink: Analytics and optimization script active.');
}})();
"""

    raw_json_ld = site.json_ld or site.json_ld_content or ""
    encoded_json_ld = json.dumps(raw_json_ld)
    return f"""
/**
 * GhostLink AI Optimization
 * Site: {site.url}
 * Target: AI Agent / Bot
 */
(function() {{
    const rawJsonLd = {encoded_json_ld};
    let jsonLdData = null;

    if (rawJsonLd) {{
        try {{
            jsonLdData = JSON.parse(rawJsonLd);
        }} catch (error) {{
            console.warn('GhostLink: Failed to parse JSON-LD payload.');
        }}
    }}

    if (jsonLdData) {{
        const script = document.createElement('script');
        script.type = 'application/ld+json';
        script.text = JSON.stringify(jsonLdData);
        document.head.appendChild(script);
        console.log('GhostLink: Optimized Schema Injected for AI Crawler.');
    }}
}})();
"""

async def log_visit_background(site_id: int, user_agent: str, bot_name: str):
    """
    Log the visit in background to avoid blocking the script delivery.
    """
    from app.db.engine import engine 
    from sqlmodel.ext.asyncio.session import AsyncSession
    from sqlalchemy.orm import sessionmaker

    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    try:
        async with async_session() as session:
            visit = BotVisit(
                site_id=site_id,
                bot_name=bot_name,
                user_agent=user_agent,
                served_asset_type="script"
            )
            session.add(visit)
            await session.commit()
    except Exception as e:
        logger.error(f"Failed to log bot visit: {e}")


async def log_bridge_events_background(
    site_id: int,
    user_agent: str,
    event_payloads: list[dict[str, str | None]],
    ingest_source: str = "batch_post",
):
    """
    Compatibility wrapper:
    enqueue raw events, then run a normalization worker pass.
    """
    if not event_payloads:
        return
    await enqueue_bridge_raw_events_background(site_id, user_agent, event_payloads, ingest_source)
    await process_bridge_raw_queue_background(site_id)


def _raw_retry_delay_seconds(attempt: int) -> int:
    safe_attempt = max(1, attempt)
    return min(BRIDGE_RAW_RETRY_MAX_SECONDS, BRIDGE_RAW_RETRY_BASE_SECONDS * (2 ** (safe_attempt - 1)))


async def enqueue_bridge_raw_events_background(
    site_id: int,
    user_agent: str,
    event_payloads: list[dict[str, str | None]],
    ingest_source: str = "batch_post",
) -> int:
    """
    Persist raw events only. Normalization is delegated to worker functions.
    """
    from app.db.engine import engine
    from sqlmodel.ext.asyncio.session import AsyncSession
    from sqlalchemy.orm import sessionmaker

    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    if not event_payloads:
        return 0

    try:
        async with async_session() as db_session:
            for payload in event_payloads:
                db_session.add(
                    BridgeEventRaw(
                        site_id=site_id,
                        event_id=_clip(payload.get("event_id"), 128),
                        ingest_source=ingest_source,
                        event_type=str(payload.get("event_type") or "custom"),
                        payload_json=json.dumps(payload, ensure_ascii=True),
                        request_user_agent=_clip(user_agent, 255),
                    )
                )
            await db_session.commit()
    except Exception as e:
        logger.error(f"Failed to enqueue bridge raw events (count={len(event_payloads)}): {e}")
        return 0

    return len(event_payloads)


async def _mark_raw_retry_or_drop(
    db_session: AsyncSession,
    row_id: int,
    error: Exception,
) -> None:
    row = await db_session.get(BridgeEventRaw, row_id)
    if row is None or row.normalized:
        return

    now_utc = datetime.utcnow()
    attempts = int(row.retry_count or 0) + 1
    row.retry_count = attempts
    row.last_error = _clip(str(error), 512)

    if attempts >= BRIDGE_RAW_MAX_RETRIES:
        row.normalized = True
        row.dropped_reason = "retry_exhausted"
        row.normalized_at = now_utc
        row.next_retry_at = None
    else:
        row.next_retry_at = now_utc + timedelta(seconds=_raw_retry_delay_seconds(attempts))

    db_session.add(row)
    await db_session.commit()


async def process_bridge_raw_queue_background(
    site_id: int,
    limit: int = BRIDGE_RAW_WORKER_BATCH_SIZE,
) -> dict[str, int]:
    """
    Normalize pending raw events into canonical BridgeEvent rows.
    Includes retry/backoff for transient processing failures.
    """
    from app.db.engine import engine
    from sqlmodel.ext.asyncio.session import AsyncSession
    from sqlalchemy.orm import sessionmaker

    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    summary = {
        "processed": 0,
        "normalized": 0,
        "dropped": 0,
        "retried": 0,
    }

    try:
        async with async_session() as db_session:
            now_utc = datetime.utcnow()
            pending_rows = (
                await db_session.exec(
                    select(BridgeEventRaw)
                    .where(
                        and_(
                            BridgeEventRaw.site_id == site_id,
                            BridgeEventRaw.normalized == False,  # noqa: E712
                            BridgeEventRaw.dropped_reason.is_(None),
                            or_(
                                BridgeEventRaw.next_retry_at.is_(None),
                                BridgeEventRaw.next_retry_at <= now_utc,
                            ),
                        )
                    )
                    .order_by(BridgeEventRaw.id.asc())
                    .limit(limit)
                )
            ).all()

            pending_ids = [int(row.id) for row in pending_rows if row.id is not None]
            for row_id in pending_ids:
                row = await db_session.get(BridgeEventRaw, row_id)
                if (
                    row is None
                    or row.normalized
                    or row.dropped_reason is not None
                ):
                    continue

                summary["processed"] += 1
                try:
                    payload = json.loads(row.payload_json or "{}")
                    if not isinstance(payload, dict):
                        raise ValueError("payload_json must decode to dict")
                except Exception:
                    row.normalized = True
                    row.dropped_reason = "invalid_payload_json"
                    row.normalized_at = now_utc
                    row.next_retry_at = None
                    row.last_error = None
                    db_session.add(row)
                    await db_session.commit()
                    summary["dropped"] += 1
                    continue

                try:
                    event_id = _clip(payload.get("event_id"), 128)
                    if event_id:
                        duplicate_exists = (
                            await db_session.exec(
                                select(BridgeEventRaw.id).where(
                                    and_(
                                        BridgeEventRaw.site_id == site_id,
                                        BridgeEventRaw.normalized == True,  # noqa: E712
                                        BridgeEventRaw.dropped_reason.is_(None),
                                        BridgeEventRaw.event_id == event_id,
                                    )
                                )
                            )
                        ).first()
                        if duplicate_exists is not None:
                            row.normalized = True
                            row.dropped_reason = "duplicate_event_id"
                            row.normalized_at = now_utc
                            row.next_retry_at = None
                            row.last_error = None
                            db_session.add(row)
                            await db_session.commit()
                            summary["dropped"] += 1
                            continue

                    event = BridgeEvent(
                        site_id=site_id,
                        session_id=_clip(payload.get("session_id"), 128),
                        event_type=_normalize_event_type(payload.get("event_type")),
                        page_url=_clip(payload.get("page_url"), 1024),
                        page_title=_clip(payload.get("page_title"), 512),
                        referrer=_clip(payload.get("referrer"), 1024),
                        language=_clip(payload.get("language"), 32),
                        timezone=_clip(payload.get("timezone"), 64),
                        viewport=_clip(payload.get("viewport"), 32),
                        user_agent=_clip(row.request_user_agent, 255),
                        timestamp=_parse_occurred_at(payload.get("occurred_at")) or datetime.utcnow(),
                    )
                    db_session.add(event)

                    row.normalized = True
                    row.dropped_reason = None
                    row.normalized_at = now_utc
                    row.retry_count = 0
                    row.next_retry_at = None
                    row.last_error = None
                    db_session.add(row)
                    await db_session.commit()
                    summary["normalized"] += 1
                except Exception as e:
                    await db_session.rollback()
                    try:
                        await _mark_raw_retry_or_drop(db_session, row_id, e)
                        retry_row = await db_session.get(BridgeEventRaw, row_id)
                        if retry_row and retry_row.dropped_reason == "retry_exhausted":
                            summary["dropped"] += 1
                        else:
                            summary["retried"] += 1
                    except Exception as inner_error:
                        await db_session.rollback()
                        logger.error(f"Failed to mark retry for raw event row_id={row_id}: {inner_error}")
    except Exception as e:
        logger.error(f"Failed to process bridge raw queue (site_id={site_id}): {e}")

    return summary


async def log_bridge_event_background(site_id: int, user_agent: str, query_params: dict[str, str]):
    """
    Save a legacy single event payload from query params.
    """
    event_payload = _bridge_event_payload_from_query(query_params)
    await enqueue_bridge_raw_events_background(site_id, user_agent, [event_payload], "legacy_get")
    await process_bridge_raw_queue_background(site_id)


def _get_cached_site_context(script_id: str, current_time: float) -> tuple[int, str] | None:
    cached = SITE_CACHE.get(script_id)
    if not cached:
        return None
    site_id, site_url, cached_at = cached
    if current_time - cached_at >= CACHE_TTL:
        SITE_CACHE.pop(script_id, None)
        return None
    return site_id, site_url


async def _resolve_site_context(
    script_id: str,
    current_time: float,
    session: AsyncSession,
) -> tuple[int, str] | None:
    site_context = _get_cached_site_context(script_id, current_time)
    if site_context is not None:
        return site_context

    statement = select(Site.id, Site.url).where(Site.script_id == script_id)
    site_result = await session.exec(statement)
    row = site_result.first()
    if row is None:
        return None
    site_id, site_url = row
    SITE_CACHE[script_id] = (site_id, site_url, current_time)
    return site_id, site_url

@router.get("/bridge/{script_id}.js")
async def get_bridge_script(
    script_id: str, 
    request: Request,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session)
):
    user_agent = request.headers.get("user-agent", "")
    detected_bot = _detect_bot(user_agent)
    is_bot = detected_bot != "Human/Browser"

    script_host = str(request.base_url).rstrip("/")

    # --- Cache Check ---
    current_time = time.time()
    # Cache key now includes is_bot
    cache_key = (script_id, is_bot)
    cached_data = SCRIPT_CACHE.get(cache_key)
    
    if cached_data:
        js_content, cached_site_id, cached_at = cached_data
        if current_time - cached_at < CACHE_TTL:
            background_tasks.add_task(log_visit_background, cached_site_id, user_agent[:255], detected_bot)
            return Response(
                content=js_content,
                media_type="application/javascript",
                headers={"Cache-Control": "public, max-age=300"},
            )

    # --- Cache Miss ---
    statement = select(Site).where(Site.script_id == script_id)
    results = await session.exec(statement)
    site = results.first()
    
    if not site:
        return Response(
            content="console.warn('GhostLink: Invalid Script ID');",
            media_type="application/javascript",
            headers={"Cache-Control": "no-store"},
        )
            
    # Log valid visits
    SITE_CACHE[script_id] = (site.id, site.url, current_time)
    background_tasks.add_task(log_visit_background, site.id, user_agent[:255], detected_bot)
    
    # --- Response Generation ---
    js_content = _build_bridge_script(site, is_bot, script_host)
    if is_bot:
        deployed = await edge_service.get_active_artifact(
            session=session,
            site_id=site.id,
            channel="production",
            artifact_type="bridge_script",
        )
        if deployed and deployed.content_body:
            js_content = deployed.content_body

    # Create Response Object
    response = Response(
        content=js_content,
        media_type="application/javascript",
        headers={"Cache-Control": "public, max-age=300"},
    )
    
    # Update Cache
    SCRIPT_CACHE[cache_key] = (js_content, site.id, current_time)
    
    return response


@router.get("/bridge/{script_id}/token")
async def get_bridge_event_token(
    script_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    current_time = time.time()
    site_context = await _resolve_site_context(script_id, current_time, session)
    if site_context is None:
        return Response(
            status_code=204,
            headers={"Cache-Control": "no-store, max-age=0"},
        )
    _site_id, site_url = site_context

    if not _validate_event_origin(request, site_url):
        return Response(
            status_code=403,
            headers={"Cache-Control": "no-store, max-age=0"},
        )

    exp, nonce, sig = _build_bridge_token(script_id)
    payload = {
        "gx": str(exp),
        "gn": nonce,
        "gs": sig,
        "expires_at": datetime.fromtimestamp(exp, tz=timezone.utc).isoformat(),
        "ttl_seconds": settings.BRIDGE_EVENT_TOKEN_TTL_SECONDS,
    }
    return JSONResponse(
        content=payload,
        headers={"Cache-Control": "no-store, max-age=0"},
    )


@router.get("/bridge/{script_id}/event")
async def collect_bridge_event(
    script_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
):
    current_time = time.time()
    site_context = await _resolve_site_context(script_id, current_time, session)
    if site_context is None:
        return Response(
            status_code=204,
            headers={"Cache-Control": "no-store, max-age=0"},
        )
    site_id, site_url = site_context

    params = dict(request.query_params)
    if not _verify_bridge_token(script_id, params.get("gx"), params.get("gn"), params.get("gs")):
        return Response(
            status_code=403,
            headers={"Cache-Control": "no-store, max-age=0"},
        )

    if not _validate_event_origin(request, site_url):
        return Response(
            status_code=403,
            headers={"Cache-Control": "no-store, max-age=0"},
        )

    user_agent = request.headers.get("user-agent", "")
    event_payload = _bridge_event_payload_from_query(params)
    background_tasks.add_task(
        enqueue_bridge_raw_events_background,
        site_id,
        user_agent,
        [event_payload],
        "legacy_get",
    )
    background_tasks.add_task(process_bridge_raw_queue_background, site_id)

    return Response(
        status_code=204,
        headers={"Cache-Control": "no-store, max-age=0"},
    )


@router.post("/bridge/{script_id}/events")
async def collect_bridge_events(
    script_id: str,
    payload: BridgeBatchRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
):
    current_time = time.time()
    site_context = await _resolve_site_context(script_id, current_time, session)
    if site_context is None:
        return Response(
            status_code=204,
            headers={"Cache-Control": "no-store, max-age=0"},
        )
    site_id, site_url = site_context

    if not _verify_bridge_token(script_id, payload.gx, payload.gn, payload.gs):
        return Response(
            status_code=403,
            headers={"Cache-Control": "no-store, max-age=0"},
        )

    if not _validate_event_origin(request, site_url):
        return Response(
            status_code=403,
            headers={"Cache-Control": "no-store, max-age=0"},
        )

    reasons: dict[str, int] = {}
    accepted_payloads: list[dict[str, str | None]] = []
    dropped_payloads: list[tuple[dict[str, str | None], str]] = []
    seen_event_ids: set[str] = set()
    events = payload.events or []

    for idx, item in enumerate(events):
        if idx >= MAX_BRIDGE_BATCH_EVENTS:
            reasons["batch_limit_exceeded"] = reasons.get("batch_limit_exceeded", 0) + 1
            dropped_payloads.append((_bridge_event_payload_from_batch(item), "batch_limit_exceeded"))
            continue

        event_id = (item.event_id or "").strip()
        if event_id and event_id in seen_event_ids:
            reasons["duplicate_event_id"] = reasons.get("duplicate_event_id", 0) + 1
            dropped_payloads.append((_bridge_event_payload_from_batch(item), "duplicate_event_id"))
            continue
        if event_id:
            seen_event_ids.add(event_id)

        accepted_payloads.append(_bridge_event_payload_from_batch(item))

    user_agent = request.headers.get("user-agent", "")
    if dropped_payloads:
        dropped_now = datetime.utcnow()
        for payload_item, reason in dropped_payloads:
            session.add(
                BridgeEventRaw(
                    site_id=site_id,
                    event_id=_clip(payload_item.get("event_id"), 128),
                    ingest_source="batch_post",
                    event_type=str(payload_item.get("event_type") or "custom"),
                    payload_json=json.dumps(payload_item, ensure_ascii=True),
                    normalized=True,
                    dropped_reason=reason,
                    request_user_agent=_clip(user_agent, 255),
                    normalized_at=dropped_now,
                )
            )
        await session.commit()

    if accepted_payloads:
        background_tasks.add_task(
            enqueue_bridge_raw_events_background,
            site_id,
            user_agent,
            accepted_payloads,
            "batch_post",
        )
        background_tasks.add_task(process_bridge_raw_queue_background, site_id)

    dropped = len(events) - len(accepted_payloads)
    return {
        "accepted": len(accepted_payloads),
        "dropped": dropped,
        "reasons": reasons,
        "server_time": datetime.now(timezone.utc).isoformat(),
    }
