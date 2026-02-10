from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import RedirectResponse
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select
from app.db.engine import get_session
from app.models.user import User
from app.core.security import get_password_hash
from jose import jwt, JWTError
from app.core.config import settings
from app.services.ui_language_service import normalize_ui_language
from starlette.templating import Jinja2Templates

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

async def get_current_user(request: Request, session: AsyncSession = Depends(get_session)):
    token = request.cookies.get("access_token")
    if not token:
        return None
    try:
        scheme, _, param = token.partition(" ")
        payload = jwt.decode(param, settings.SECRET_KEY, algorithms=["HS256"])
        email = payload.get("sub")
        if email is None:
            return None
    except JWTError:
        return None
        
    query = select(User).where(User.email == email)
    result = await session.exec(query)
    user = result.first()
    return user

@router.get("/profile")
async def profile_page(request: Request, user: User = Depends(get_current_user)):
    if not user:
        return RedirectResponse(url="/auth/login", status_code=status.HTTP_303_SEE_OTHER)
    return templates.TemplateResponse("pages/profile.html", {"request": request, "user": user, "active_page": "profile"})

@router.post("/profile")
async def update_profile(
    request: Request,
    full_name: str = Form(...),
    password: str = Form(None),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    if not user:
        return RedirectResponse(url="/auth/login", status_code=status.HTTP_303_SEE_OTHER)
    
    user.full_name = full_name
    if password:
        user.hashed_password = get_password_hash(password)
    
    session.add(user)
    await session.commit()
    await session.refresh(user)
    
    return templates.TemplateResponse("pages/profile.html", {
        "request": request, 
        "user": user, 
        "active_page": "profile",
        "success": "Profile updated successfully"
    })


@router.post("/ui-language")
async def update_ui_language(
    language: str = Form("auto"),
    next_url: str = Form("/dashboard"),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    if not user:
        return RedirectResponse(url="/auth/login", status_code=status.HTTP_303_SEE_OTHER)

    try:
        normalized = normalize_ui_language(language)
        user.preferred_ui_language = normalized
        session.add(user)
        await session.commit()
        await session.refresh(user)
    except Exception as e:
        # Log error but don't crash the user experience
        # logger.error(f"Failed to update UI language: {e}")
        pass

    safe_next = next_url if next_url.startswith("/") else "/dashboard"
    response = RedirectResponse(url=safe_next, status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(
        key="ghostlink_ui_language",
        value=normalize_ui_language(language),
        max_age=60 * 60 * 24 * 365,
        httponly=False,
        samesite="lax",
    )
    return response

@router.get("/ui-language")
async def get_ui_language_redirect():
    # Prevent 405 Method Not Allowed if accessed via GET
    return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
