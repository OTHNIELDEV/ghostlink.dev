from datetime import datetime
from urllib.parse import urlparse, urlunparse

from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, Request
from sqlalchemy.orm import sessionmaker
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select, and_, func
from app.db.engine import engine, get_session
from app.models.site import Site
from app.models.user import User
from app.models.organization import Membership
from app.services.core_engine import process_site_background as core_process_site_background
from app.services.subscription_service import subscription_service
from app.billing.plans import get_plan_limit
from app.routers.users import get_current_user
from starlette.templating import Jinja2Templates

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

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

async def process_site_background(site_id: int):
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

    await core_process_site_background(site_id)

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

@router.post("/sites")
async def add_site(
    request: Request, 
    background_tasks: BackgroundTasks,
    url: str = Form(...), 
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
        should_start_processing = await _set_site_pending(site, session)
    else:
        site = Site(
            url=normalized_url,
            status="pending",
            updated_at=datetime.utcnow(),
            org_id=effective_org_id,
            owner_id=current_user.id
        )
        session.add(site)
        await session.commit()
        await session.refresh(site)
        should_start_processing = True

    if should_start_processing:
        background_tasks.add_task(process_site_background, site.id)
    
    return templates.TemplateResponse("components/site_card.html", {"request": request, "site": site})

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
    
    should_start_processing = await _set_site_pending(site, session)
    if should_start_processing:
        background_tasks.add_task(process_site_background, site.id)
    
    return templates.TemplateResponse("components/site_card.html", {"request": request, "site": site})

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

    return templates.TemplateResponse("components/site_card.html", {"request": request, "site": site})
