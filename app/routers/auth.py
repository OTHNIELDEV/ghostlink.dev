from datetime import timedelta
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, status, Request, Response, Form
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.responses import RedirectResponse
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select
from app.db.engine import get_session
from app.models.user import User
from app.models.organization import Organization, Membership
from app.models.billing import Subscription
from app.core.security import create_access_token, get_password_hash, verify_password
from app.core.config import settings
from starlette.templating import Jinja2Templates
import secrets
import string

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

def generate_org_slug(name: str) -> str:
    base = "".join(c.lower() if c.isalnum() else "-" for c in name)
    base = "-".join(filter(None, base.split("-")))
    suffix = "".join(secrets.choice(string.ascii_lowercase + string.digits) for _ in range(6))
    return f"{base}-{suffix}"

async def create_personal_organization(session: AsyncSession, user: User):
    org_name = f"{user.full_name or user.email}'s Workspace"
    slug = generate_org_slug(org_name)
    
    org = Organization(
        name=org_name,
        slug=slug,
        billing_email=user.email
    )
    session.add(org)
    await session.flush()
    
    membership = Membership(
        org_id=org.id,
        user_id=user.id,
        role="owner"
    )
    session.add(membership)
    
    subscription = Subscription(
        org_id=org.id,
        plan_code="free",
        status="active"
    )
    session.add(subscription)
    
    await session.commit()
    return org

@router.get("/login")
async def login_page(request: Request):
    return templates.TemplateResponse("auth/login.html", {"request": request})

@router.post("/login")
async def login(
    request: Request,
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    session: AsyncSession = Depends(get_session)
):
    query = select(User).where(User.email == form_data.username)
    result = await session.exec(query)
    user = result.first()
    
    if not user or not verify_password(form_data.password, user.hashed_password):
        return templates.TemplateResponse("auth/login.html", {"request": request, "error": "Incorrect email or password"})
    
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(subject=user.email, expires_delta=access_token_expires)
    
    response = RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(key="access_token", value=f"Bearer {access_token}", httponly=True)
    return response

@router.get("/register")
async def register_page(request: Request):
    return templates.TemplateResponse("auth/register.html", {"request": request})

@router.post("/register")
async def register(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    full_name: str = Form(None),
    session: AsyncSession = Depends(get_session)
):
    query = select(User).where(User.email == email)
    result = await session.exec(query)
    if result.first():
         return templates.TemplateResponse("auth/register.html", {"request": request, "error": "Email already registered"})
    
    hashed_pw = get_password_hash(password)
    new_user = User(email=email, hashed_password=hashed_pw, full_name=full_name)
    
    try:
        session.add(new_user)
        await session.flush()
        
        await create_personal_organization(session, new_user)
        await session.refresh(new_user)
        
        await session.commit()
    except Exception as e:
        await session.rollback()
        import logging
        logging.error(f"Registration failed: {e}")
        return templates.TemplateResponse("auth/register.html", {"request": request, "error": f"Registration failed due to a server error. Please try again later. (Error: {str(e)})"})
    
    access_token = create_access_token(subject=new_user.email)
    response = RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(key="access_token", value=f"Bearer {access_token}", httponly=True)
    return response

@router.get("/logout")
async def logout(response: Response):
    response = RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie(key="access_token")
    return response

from app.core.oauth import oauth

@router.get("/login/{provider}")
async def login_via_provider(request: Request, provider: str):
    redirect_uri = request.url_for('auth_callback', provider=provider)
    return await oauth.create_client(provider).authorize_redirect(request, redirect_uri)

@router.get("/auth/{provider}/callback", name="auth_callback")
async def auth_callback(request: Request, provider: str, session: AsyncSession = Depends(get_session)):
    token = await oauth.create_client(provider).authorize_access_token(request)
    
    user_email = ""
    user_name = ""
    provider_user_id = ""
    
    if provider == 'google':
        user_info = token.get('userinfo')
        if not user_info:
            resp = await oauth.google.get('https://www.googleapis.com/oauth2/v3/userinfo', token=token)
            user_info = resp.json()
            
        user_email = user_info.get('email')
        user_name = user_info.get('name')
        provider_user_id = user_info.get('sub')
        
    elif provider == 'github':
        resp = await oauth.github.get('user', token=token)
        user_info = resp.json()
        user_name = user_info.get('name') or user_info.get('login')
        provider_user_id = str(user_info.get('id'))
        
        resp_emails = await oauth.github.get('user/emails', token=token)
        emails = resp_emails.json()
        for e in emails:
            if e['primary'] and e['verified']:
                user_email = e['email']
                break
        if not user_email:
             user_email = emails[0]['email']

    if not user_email:
        raise HTTPException(status_code=400, detail="Could not retrieve email from provider")

    query = select(User).where(User.email == user_email)
    result = await session.exec(query)
    user = result.first()
    
    is_new_user = False
    if not user:
        is_new_user = True
        user = User(
            email=user_email,
            full_name=user_name,
            provider=provider,
            provider_id=provider_user_id,
            is_active=True
        )
        session.add(user)
        await session.flush()
        await create_personal_organization(session, user)
    else:
        if not user.provider:
            user.provider = provider
            user.provider_id = provider_user_id
            session.add(user)
            await session.commit()
            
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(subject=user.email, expires_delta=access_token_expires)
    
    redirect_url = "/dashboard"
    if is_new_user:
        redirect_url = "/dashboard?welcome=new"
    
    response = RedirectResponse(url=redirect_url, status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(key="access_token", value=f"Bearer {access_token}", httponly=True)
    return response
