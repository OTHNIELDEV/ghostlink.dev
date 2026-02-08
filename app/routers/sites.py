from datetime import datetime
from urllib.parse import urlparse, urlunparse

from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import sessionmaker
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select, and_, func
from app.db.engine import engine, get_session
from app.models.site import Site
from app.models.user import User
from app.models.organization import Membership, Organization
from app.services.core_engine import process_site_background as core_process_site_background
from app.services.language_service import (
    LANGUAGE_OPTIONS,
    language_label,
    normalize_language_preference,
    resolve_effective_language_code,
)
from app.services.subscription_service import subscription_service
from app.billing.plans import get_plan_limit
from app.routers.users import get_current_user
from starlette.templating import Jinja2Templates

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


def _hydrate_site_language(site: Site, accept_language: str | None = None) -> None:
    preferred = normalize_language_preference(site.preferred_language)
    effective = resolve_effective_language_code(
        preferred_language=preferred,
        site_url=site.url,
        accept_language=accept_language,
    )
    site.preferred_language = preferred
    object.__setattr__(site, "effective_language_code", effective)
    object.__setattr__(site, "effective_language_label", language_label(effective))


def _resolve_site_template(request: Request) -> str:
    hx_target = (request.headers.get("HX-Target") or "").strip()
    if hx_target.startswith("site-row-"):
        return "components/site_row.html"
    return "components/site_card.html"

def normalize_site_url(raw_url: str) -> str:
    candidate = (raw_url or "").strip()
    if not candidate:
        raise ValueError("URL is required.")

    if "://" not in candidate:
        candidate = f"https://{candidate}"

    parsed = urlparse(candidate)
    if not parsed.netloc:
        raise ValueError("Please provide a valid website URL.")

    path = parsed.path or ""
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")

    return urlunparse(
        (
            parsed.scheme.lower() or "https",
            parsed.netloc.lower(),
            path,
            "",
            "",
            "",
        )
    )

async def _set_site_pending(site: Site, session: AsyncSession) -> bool:
    if site.status == "pending":
        return False

    site.status = "pending"
    site.error_msg = None
    site.updated_at = datetime.utcnow()
    session.add(site)
    await session.commit()
    await session.refresh(site)
    return True

async def process_site_background(site_id: int, language: str | None = None):
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        site = await session.get(Site, site_id)
        if not site:
            return

        org_id = site.org_id
        if org_id is not None:
            await subscription_service.record_usage(
                session, org_id, "site_scans_per_month", 1
            )

    await core_process_site_background(site_id, language=language)

async def get_org_id_for_user(
    session: AsyncSession,
    user: User,
    requested_org_id: int = None
) -> int:
    if requested_org_id:
        membership = await session.exec(
            select(Membership).where(
                and_(
                    Membership.org_id == requested_org_id,
                    Membership.user_id == user.id
                )
            )
        )
        if membership.first():
            return requested_org_id
        raise HTTPException(status_code=403, detail="Access denied to organization")
    
    result = await session.exec(
        select(Membership).where(Membership.user_id == user.id)
    )
    first_membership = result.first()
    
    if first_membership:
        return first_membership.org_id
    
    raise HTTPException(status_code=400, detail="No organization found")


async def _get_membership(
    session: AsyncSession,
    org_id: int,
    user_id: int | None,
) -> Membership | None:
    if user_id is None:
        return None
    result = await session.exec(
        select(Membership).where(
            and_(
                Membership.org_id == org_id,
                Membership.user_id == user_id,
            )
        )
    )
    return result.first()

@router.post("/sites")
async def add_site(
    request: Request, 
    background_tasks: BackgroundTasks,
    url: str = Form(...), 
    language: str | None = Form(None),
    org_id: int = Form(None),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    if not current_user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    effective_org_id = await get_org_id_for_user(session, current_user, org_id)
    
    subscription = await subscription_service.get_or_create_subscription(
        session, effective_org_id
    )
    plan_code = subscription.plan_code
    
    result = await session.exec(
        select(func.count()).select_from(Site).where(Site.org_id == effective_org_id)
    )
    current_sites = result.one()
    max_sites = get_plan_limit(plan_code, "sites")
    
    if max_sites != -1 and current_sites >= max_sites:
        raise HTTPException(
            status_code=403,
            detail=f"Site limit reached ({max_sites}). Upgrade your plan to add more sites."
        )
    
    try:
        normalized_url = normalize_site_url(url)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    organization = await session.get(Organization, effective_org_id)
    org_preferred_language = normalize_language_preference(
        organization.preferred_language if organization else "auto"
    )
    preferred_language = normalize_language_preference(language) if language is not None else org_preferred_language

    statement = select(Site).where(
        and_(
            Site.url == normalized_url,
            Site.org_id == effective_org_id
        )
    )
    existing_result = await session.exec(statement)
    site = existing_result.first()

    should_start_processing = False
    if site:
        language_changed = site.preferred_language != preferred_language
        if language_changed:
            site.preferred_language = preferred_language
            site.updated_at = datetime.utcnow()
            session.add(site)
            await session.commit()
            await session.refresh(site)
        should_start_processing = await _set_site_pending(site, session)
    else:
        site = Site(
            url=normalized_url,
            status="pending",
            updated_at=datetime.utcnow(),
            preferred_language=preferred_language,
            org_id=effective_org_id,
            owner_id=current_user.id
        )
        session.add(site)
        await session.commit()
        await session.refresh(site)
        should_start_processing = True

    if should_start_processing:
        background_tasks.add_task(process_site_background, site.id)

    _hydrate_site_language(site, request.headers.get("accept-language"))
    return templates.TemplateResponse(
        "components/site_card.html",
        {
            "request": request,
            "site": site,
            "language_options": LANGUAGE_OPTIONS,
        },
    )


@router.post("/sites/language")
async def update_org_language(
    request: Request,
    background_tasks: BackgroundTasks,
    language: str = Form("auto"),
    org_id: int = Form(None),
    rescan: str = Form("true"),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    if not current_user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    effective_org_id = await get_org_id_for_user(session, current_user, org_id)
    membership = await _get_membership(session, effective_org_id, current_user.id)
    if not membership or membership.role not in {"owner", "admin"}:
        raise HTTPException(status_code=403, detail="Only owner/admin can change org language")

    normalized_language = normalize_language_preference(language)
    should_rescan = str(rescan).strip().lower() in {"1", "true", "yes", "y", "on"}

    organization = await session.get(Organization, effective_org_id)
    if not organization:
        raise HTTPException(status_code=404, detail="Organization not found")
    organization.preferred_language = normalized_language
    organization.updated_at = datetime.utcnow()
    session.add(organization)

    sites = (
        await session.exec(
            select(Site).where(Site.org_id == effective_org_id).order_by(Site.created_at.desc())
        )
    ).all()
    updated_sites = 0
    now = datetime.utcnow()
    for site in sites:
        if site.preferred_language != normalized_language:
            site.preferred_language = normalized_language
            site.updated_at = now
            session.add(site)
            updated_sites += 1

    await session.commit()
    for site in sites:
        await session.refresh(site)

    started_rescans = 0
    quota_skipped = 0
    if should_rescan and sites:
        candidates = [site for site in sites if site.status not in {"pending", "processing"}]
        allowed, current, limit = await subscription_service.check_quota(
            session, effective_org_id, "site_scans_per_month"
        )
        if allowed:
            if limit == -1:
                start_budget = len(candidates)
            else:
                start_budget = max(0, int(limit) - int(current))

            for site in candidates:
                if started_rescans >= start_budget:
                    break
                should_start_processing = await _set_site_pending(site, session)
                if should_start_processing:
                    background_tasks.add_task(process_site_background, site.id)
                    started_rescans += 1

            quota_skipped = max(0, len(candidates) - started_rescans)
        else:
            quota_skipped = len(candidates)

    return JSONResponse(
        {
            "status": "ok",
            "org_id": effective_org_id,
            "language": normalized_language,
            "updated_sites": updated_sites,
            "total_sites": len(sites),
            "rescan_requested": should_rescan,
            "rescan_started": started_rescans,
            "rescan_skipped_quota": quota_skipped,
        }
    )

@router.delete("/sites/{site_id}")
async def delete_site(
    site_id: int, 
    org_id: int = None,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    if not current_user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    effective_org_id = await get_org_id_for_user(session, current_user, org_id)
    
    from app.routers.bridge import invalidate_script_cache

    site = await session.get(Site, site_id)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")
    
    if site.org_id != effective_org_id:
        raise HTTPException(status_code=403, detail="Not authorized to delete this site")
    
    invalidate_script_cache(site.script_id)
    await session.delete(site)
    await session.commit()
    
    return ""

@router.post("/sites/{site_id}/generate")
async def generate_site_assets(
    site_id: int, 
    background_tasks: BackgroundTasks, 
    request: Request,
    language: str | None = Form(None),
    org_id: int = None,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    if not current_user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    effective_org_id = await get_org_id_for_user(session, current_user, org_id)
    
    site = await session.get(Site, site_id)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found.")
    
    if site.org_id != effective_org_id:
        raise HTTPException(status_code=403, detail="Not authorized.")
    
    allowed, current, limit = await subscription_service.check_quota(
        session, effective_org_id, "site_scans_per_month"
    )
    
    if not allowed:
        raise HTTPException(
            status_code=403,
            detail=f"Monthly scan limit reached ({limit}). Upgrade your plan for more scans."
        )
    
    language_changed = False
    if language is not None:
        preferred_language = normalize_language_preference(language)
        if site.preferred_language != preferred_language:
            site.preferred_language = preferred_language
            site.updated_at = datetime.utcnow()
            session.add(site)
            language_changed = True

    if language_changed and site.status == "pending":
        await session.commit()
        await session.refresh(site)

    should_start_processing = await _set_site_pending(site, session)
    if should_start_processing:
        background_tasks.add_task(process_site_background, site.id)

    _hydrate_site_language(site, request.headers.get("accept-language"))
    template_name = _resolve_site_template(request)
    return templates.TemplateResponse(
        template_name,
        {
            "request": request,
            "site": site,
            "language_options": LANGUAGE_OPTIONS,
        },
    )


@router.post("/sites/{site_id}/language")
async def update_site_language(
    request: Request,
    background_tasks: BackgroundTasks,
    site_id: int,
    language: str = Form("auto"),
    org_id: int = None,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    if not current_user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    effective_org_id = await get_org_id_for_user(session, current_user, org_id)

    site = await session.get(Site, site_id)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found.")
    if site.org_id != effective_org_id:
        raise HTTPException(status_code=403, detail="Not authorized.")

    normalized_language = normalize_language_preference(language)
    language_changed = site.preferred_language != normalized_language

    site.preferred_language = normalized_language
    site.updated_at = datetime.utcnow()
    session.add(site)

    # Site-wide language change should immediately affect future assets.
    # If language changed, queue a new scan so report/json-ld/llms are regenerated.
    should_start_processing = False
    if language_changed:
        allowed, _current, limit = await subscription_service.check_quota(
            session, effective_org_id, "site_scans_per_month"
        )
        if not allowed:
            raise HTTPException(
                status_code=403,
                detail=f"Monthly scan limit reached ({limit}). Upgrade your plan for more scans.",
            )
        should_start_processing = await _set_site_pending(site, session)
    else:
        await session.commit()
        await session.refresh(site)

    if should_start_processing:
        background_tasks.add_task(process_site_background, site.id)

    _hydrate_site_language(site, request.headers.get("accept-language"))
    template_name = _resolve_site_template(request)
    return templates.TemplateResponse(
        template_name,
        {
            "request": request,
            "site": site,
            "language_options": LANGUAGE_OPTIONS,
        },
    )

@router.get("/sites/{site_id}/card")
async def get_site_card(
    request: Request, 
    site_id: int, 
    org_id: int = None,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    if not current_user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    effective_org_id = await get_org_id_for_user(session, current_user, org_id)
    
    site = await session.get(Site, site_id)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found.")
    
    if site.org_id != effective_org_id:
        raise HTTPException(status_code=403, detail="Not authorized.")

    _hydrate_site_language(site, request.headers.get("accept-language"))
    return templates.TemplateResponse(
        "components/site_card.html",
        {
            "request": request,
            "site": site,
            "language_options": LANGUAGE_OPTIONS,
        },
    )


@router.get("/sites/{site_id}/row")
async def get_site_row(
    request: Request,
    site_id: int,
    org_id: int = None,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    if not current_user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    effective_org_id = await get_org_id_for_user(session, current_user, org_id)

    site = await session.get(Site, site_id)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found.")

    if site.org_id != effective_org_id:
        raise HTTPException(status_code=403, detail="Not authorized.")

    _hydrate_site_language(site, request.headers.get("accept-language"))
    return templates.TemplateResponse(
        "components/site_row.html",
        {
            "request": request,
            "site": site,
            "language_options": LANGUAGE_OPTIONS,
        },
    )
