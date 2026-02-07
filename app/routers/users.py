from typing import Annotated
from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import RedirectResponse
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select
from app.db.engine import get_session
from app.models.user import User
from app.core.security import get_password_hash
from jose import jwt, JWTError
from app.core.config import settings
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
