from fastapi import APIRouter, Depends, Request, Form, HTTPException
from sqlmodel import Session, select
from app.db.engine import get_session
from app.models.site import Site
from app.services.language_service import (
    LANGUAGE_OPTIONS,
    language_label,
    normalize_language_preference,
    resolve_effective_language_code,
)
from fastapi.responses import HTMLResponse, JSONResponse
from starlette.templating import Jinja2Templates

templates = Jinja2Templates(directory="app/templates")
import json
import random
from datetime import datetime, timedelta

router = APIRouter()


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

@router.post("/dashboard/sites/{site_id}/update_json", response_class=HTMLResponse)
async def update_site_json(
    site_id: int,
    request: Request,
    json_content: str = Form(...),
    session: Session = Depends(get_session)
):
    site = await session.get(Site, site_id)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")

    try:
        # Validate JSON
        json_obj = json.loads(json_content)
        site.json_ld_content = json.dumps(json_obj, indent=2)
        site.json_ld = json.dumps(json_obj, ensure_ascii=False)
        site.updated_at = datetime.utcnow()
        session.add(site)
        await session.commit()
        await session.refresh(site)
        _hydrate_site_language(site, request.headers.get("accept-language"))
        
        # Return the updated card or a success toast
        context = {"request": request, "site": site, "language_options": LANGUAGE_OPTIONS}
        return templates.TemplateResponse("components/site_card.html", context)
    except json.JSONDecodeError:
         # In a real app, maybe return a partial with error or an OOB swap for error message
        raise HTTPException(status_code=400, detail="Invalid JSON format")

@router.get("/dashboard/sites/{site_id}/analytics")
async def get_site_analytics(site_id: int):
    # Mock data for charts
    days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    
    # Generate realistic looking bot traffic data
    bot_visits = [random.randint(5, 50) for _ in range(7)]
    human_visits = [random.randint(20, 150) for _ in range(7)]
    
    return JSONResponse({
        "labels": days,
        "datasets": [
            {
                "label": "Bot Crawlers",
                "data": bot_visits,
                "borderColor": "#10b981", # Emerald 500
                "backgroundColor": "rgba(16, 185, 129, 0.1)",
                "fill": True,
                "tension": 0.4
            },
            {
                "label": "Human Visitors",
                "data": human_visits,
                "borderColor": "#6366f1", # Indigo 500
                "backgroundColor": "rgba(99, 102, 241, 0.1)",
                "fill": True,
                "tension": 0.4
            }
        ]
    })
