import base64
import hashlib
import hmac
import json
import logging
import secrets
import time
from urllib.parse import urlparse

from fastapi import APIRouter, BackgroundTasks, Depends, Request, Response
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select
from app.core.config import settings
from app.db.engine import get_session
from app.models.site import Site
from app.models.analytics import BotVisit, BridgeEvent
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


def _build_bridge_script(site: Site, is_bot: bool, script_host: str) -> str:
    """
    Builds the JS script.
    - If Bot: Injects the full JSON-LD.
    - If Human: Runs lightweight analytics events for better visibility.
    """
    if not is_bot:
        analytics_endpoint = f"{script_host}/api/bridge/{site.script_id}/event"
        token_exp, token_nonce, token_sig = _build_bridge_token(site.script_id)
        endpoint_b64 = _b64(analytics_endpoint)
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
    const scriptId = {json.dumps(site.script_id)};
    const tokenExp = {token_exp};
    const tokenNonce = decode({json.dumps(nonce_b64)});
    const tokenSig = decode({json.dumps(sig_b64)});
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

    function sendEvent(eventType) {{
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

    sendEvent('pageview');
    setTimeout(() => sendEvent('engaged_15s'), 15000);

    document.addEventListener('visibilitychange', () => {{
        if (document.visibilityState === 'hidden') {{
            sendEvent('hidden');
        }}
    }}, {{ passive: true }});

    window.addEventListener('pagehide', () => sendEvent('leave'), {{ passive: true }});
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


async def log_bridge_event_background(site_id: int, user_agent: str, query_params: dict[str, str]):
    """
    Save human-side interaction events without blocking page rendering.
    """
    from app.db.engine import engine
    from sqlmodel.ext.asyncio.session import AsyncSession
    from sqlalchemy.orm import sessionmaker

    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    event_type = (query_params.get("e") or "pageview").lower()
    if event_type not in {"pageview", "engaged_15s", "hidden", "leave", "heartbeat"}:
        event_type = "custom"

    try:
        async with async_session() as db_session:
            event = BridgeEvent(
                site_id=site_id,
                session_id=_clip(query_params.get("sid"), 128),
                event_type=event_type,
                page_url=_clip(query_params.get("p"), 1024),
                page_title=_clip(query_params.get("t"), 512),
                referrer=_clip(query_params.get("r"), 1024),
                language=_clip(query_params.get("lang"), 32),
                timezone=_clip(query_params.get("tz"), 64),
                viewport=_clip(query_params.get("vp"), 32),
                user_agent=_clip(user_agent, 255),
            )
            db_session.add(event)
            await db_session.commit()
    except Exception as e:
        logger.error(f"Failed to log bridge event: {e}")


def _get_cached_site_context(script_id: str, current_time: float) -> tuple[int, str] | None:
    cached = SITE_CACHE.get(script_id)
    if not cached:
        return None
    site_id, site_url, cached_at = cached
    if current_time - cached_at >= CACHE_TTL:
        SITE_CACHE.pop(script_id, None)
        return None
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


@router.get("/bridge/{script_id}/event")
async def collect_bridge_event(
    script_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
):
    current_time = time.time()
    site_context = _get_cached_site_context(script_id, current_time)

    if site_context is None:
        statement = select(Site.id, Site.url).where(Site.script_id == script_id)
        site_result = await session.exec(statement)
        row = site_result.first()
        if row is None:
            return Response(
                status_code=204,
                headers={"Cache-Control": "no-store, max-age=0"},
            )
        site_id, site_url = row
        SITE_CACHE[script_id] = (site_id, site_url, current_time)
    else:
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
    background_tasks.add_task(log_bridge_event_background, site_id, user_agent, params)

    return Response(
        status_code=204,
        headers={"Cache-Control": "no-store, max-age=0"},
    )
