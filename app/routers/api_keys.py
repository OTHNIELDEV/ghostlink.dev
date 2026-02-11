from fastapi import APIRouter, Depends, HTTPException, Request, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select, and_
from typing import List
from datetime import datetime, timedelta
from app.core.rbac import parse_org_id, require_org_membership
from app.db.engine import get_session
from app.models.user import User
from app.models.api_key import (
    ApiKey, ApiKeyCreate, ApiKeyRead, ApiKeyWithSecret, 
    generate_api_key
)
from app.models.organization import Membership
from app.routers.users import get_current_user
from app.services.audit_service import audit_service
from app.services.subscription_service import subscription_service
from app.billing.plan_compat import normalize_plan_code
import hashlib

router = APIRouter(tags=["api-keys"])
security = HTTPBearer()

async def get_org_membership_from_request(
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user)
) -> Membership:
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    org_id = request.query_params.get("org_id") or request.headers.get("X-Organization-ID")
    org_id_int = parse_org_id(org_id)
    return await require_org_membership(session, user, org_id_int)


async def get_org_from_request(
    membership: Membership = Depends(get_org_membership_from_request),
) -> int:
    return membership.org_id

async def verify_api_key(
    credentials: HTTPAuthorizationCredentials = Security(security),
    session: AsyncSession = Depends(get_session)
) -> ApiKey:
    api_key = credentials.credentials
    
    if not api_key.startswith("gl_"):
        raise HTTPException(status_code=401, detail="Invalid API key format")
    
    key_hash = hashlib.sha256(api_key.encode()).hexdigest()
    
    result = await session.exec(
        select(ApiKey).where(
            and_(
                ApiKey.key_hash == key_hash,
                ApiKey.is_active == True
            )
        )
    )
    
    key_record = result.first()
    
    if not key_record:
        raise HTTPException(status_code=401, detail="Invalid API key")
    
    if key_record.expires_at and key_record.expires_at < datetime.utcnow():
        raise HTTPException(status_code=401, detail="API key expired")
    
    key_record.last_used_at = datetime.utcnow()
    session.add(key_record)
    await session.commit()
    
    return key_record

@router.post("", response_model=ApiKeyWithSecret)
async def create_api_key(
    key_data: ApiKeyCreate,
    membership: Membership = Depends(get_org_membership_from_request),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user)
):
    org_id = membership.org_id
    if membership.role not in {"owner", "admin"}:
        raise HTTPException(status_code=403, detail="Only owners/admins can manage API keys")

    can_use_api = await subscription_service.can_use_feature(
        session, org_id, "api_access"
    )
    
    if not can_use_api:
        raise HTTPException(
            status_code=403, 
            detail="API access not available on current plan"
        )
    
    plan = await subscription_service.get_or_create_subscription(session, org_id)
    
    result = await session.exec(
        select(ApiKey).where(ApiKey.org_id == org_id)
    )
    existing_keys = len(result.all())
    
    normalized_plan_code = normalize_plan_code(plan.plan_code)

    max_keys = 5
    if normalized_plan_code == "pro":
        max_keys = 20
    elif normalized_plan_code == "enterprise":
        max_keys = -1
    
    if max_keys != -1 and existing_keys >= max_keys:
        raise HTTPException(
            status_code=400,
            detail=f"Maximum number of API keys ({max_keys}) reached for your plan"
        )
    
    raw_key, prefix, key_hash = generate_api_key()
    
    expires_at = None
    if key_data.expires_days:
        expires_at = datetime.utcnow() + timedelta(days=key_data.expires_days)
    
    api_key = ApiKey(
        org_id=org_id,
        name=key_data.name,
        key_prefix=prefix,
        key_hash=key_hash,
        scopes=key_data.scopes,
        expires_at=expires_at,
        created_by=user.id
    )
    
    session.add(api_key)
    await session.commit()
    await session.refresh(api_key)
    await audit_service.log_event(
        session=session,
        org_id=org_id,
        action="api_key.created",
        actor_user_id=user.id,
        resource_type="api_key",
        resource_id=str(api_key.id),
        metadata={"name": api_key.name, "scopes": api_key.scopes},
        commit=True,
    )
    
    return ApiKeyWithSecret(
        id=api_key.id,
        name=api_key.name,
        key=raw_key,
        key_prefix=prefix,
        scopes=api_key.scopes,
        expires_at=api_key.expires_at,
        created_at=api_key.created_at
    )

@router.get("", response_model=List[ApiKeyRead])
async def list_api_keys(
    membership: Membership = Depends(get_org_membership_from_request),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user)
):
    org_id = membership.org_id
    result = await session.exec(
        select(ApiKey).where(ApiKey.org_id == org_id)
    )
    
    keys = []
    for key in result.all():
        keys.append(ApiKeyRead(
            id=key.id,
            name=key.name,
            key_prefix=key.key_prefix,
            scopes=key.scopes,
            last_used_at=key.last_used_at,
            expires_at=key.expires_at,
            is_active=key.is_active,
            created_at=key.created_at
        ))
    
    return keys

@router.delete("/{key_id}")
async def revoke_api_key(
    key_id: int,
    membership: Membership = Depends(get_org_membership_from_request),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user)
):
    org_id = membership.org_id
    if membership.role not in {"owner", "admin"}:
        raise HTTPException(status_code=403, detail="Only owners/admins can manage API keys")

    result = await session.exec(
        select(ApiKey).where(
            and_(
                ApiKey.id == key_id,
                ApiKey.org_id == org_id
            )
        )
    )
    
    key = result.first()
    
    if not key:
        raise HTTPException(status_code=404, detail="API key not found")
    
    key.is_active = False
    session.add(key)
    await session.commit()
    await audit_service.log_event(
        session=session,
        org_id=org_id,
        action="api_key.revoked",
        actor_user_id=user.id,
        resource_type="api_key",
        resource_id=str(key.id),
        metadata={"name": key.name},
        commit=True,
    )
    
    return {"status": "revoked"}
