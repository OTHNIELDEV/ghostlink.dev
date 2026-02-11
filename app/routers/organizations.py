from fastapi import APIRouter, Depends, HTTPException
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select, and_, func
from typing import List
from datetime import datetime
from app.db.engine import get_session
from app.models.user import User
from app.models.organization import Organization, Membership, OrganizationCreate, OrganizationRead, OrganizationUpdate
from app.models.billing import Subscription
from app.routers.users import get_current_user
from app.services.subscription_service import subscription_service
from app.billing.plan_compat import get_plan_limit
import secrets
import string

router = APIRouter(tags=["organizations"])

def generate_org_slug(name: str) -> str:
    base = "".join(c.lower() if c.isalnum() else "-" for c in name)
    base = "-".join(filter(None, base.split("-")))
    suffix = "".join(secrets.choice(string.ascii_lowercase + string.digits) for _ in range(6))
    return f"{base}-{suffix}"


async def _enforce_team_member_limit(session: AsyncSession, org_id: int):
    subscription = await subscription_service.get_or_create_subscription(session, org_id)
    team_limit = get_plan_limit(subscription.plan_code, "team_members")
    if team_limit == -1:
        return

    result = await session.exec(
        select(func.count(Membership.user_id)).where(Membership.org_id == org_id)
    )
    current_members = result.one() or 0
    if current_members >= team_limit:
        raise HTTPException(
            status_code=403,
            detail=f"Team member limit reached ({team_limit}). Upgrade your plan to invite more members."
        )

@router.post("", response_model=OrganizationRead)
async def create_organization(
    org_data: OrganizationCreate,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user)
):
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    if org_data.slug:
        existing = await session.exec(
            select(Organization).where(Organization.slug == org_data.slug)
        )
        if existing.first():
            raise HTTPException(status_code=400, detail="Organization slug already exists")
    else:
        org_data.slug = generate_org_slug(org_data.name)
    
    org = Organization(
        name=org_data.name,
        slug=org_data.slug,
        description=org_data.description,
        website=org_data.website,
        billing_email=user.email
    )
    
    session.add(org)
    await session.commit()
    await session.refresh(org)
    
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

@router.get("", response_model=List[OrganizationRead])
async def list_organizations(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user)
):
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    result = await session.exec(
        select(Organization)
        .join(Membership)
        .where(Membership.user_id == user.id)
        .where(Organization.is_active == True)
    )
    
    return result.all()

@router.get("/{org_id}", response_model=OrganizationRead)
async def get_organization(
    org_id: int,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user)
):
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    membership = await session.exec(
        select(Membership).where(
            and_(
                Membership.org_id == org_id,
                Membership.user_id == user.id
            )
        )
    )
    
    if not membership.first():
        raise HTTPException(status_code=403, detail="Access denied")
    
    result = await session.exec(
        select(Organization).where(Organization.id == org_id)
    )
    org = result.first()
    
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")
    
    return org

@router.patch("/{org_id}", response_model=OrganizationRead)
async def update_organization(
    org_id: int,
    org_data: OrganizationUpdate,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user)
):
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    membership = await session.exec(
        select(Membership).where(
            and_(
                Membership.org_id == org_id,
                Membership.user_id == user.id,
                Membership.role.in_(["owner", "admin"])
            )
        )
    )
    
    if not membership.first():
        raise HTTPException(status_code=403, detail="Access denied")
    
    result = await session.exec(
        select(Organization).where(Organization.id == org_id)
    )
    org = result.first()
    
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")
    
    if org_data.name:
        org.name = org_data.name
    if org_data.description is not None:
        org.description = org_data.description
    if org_data.website is not None:
        org.website = org_data.website
    if org_data.avatar_url is not None:
        org.avatar_url = org_data.avatar_url
    if org_data.billing_email is not None:
        org.billing_email = org_data.billing_email
    
    org.updated_at = datetime.utcnow()
    
    session.add(org)
    await session.commit()
    await session.refresh(org)
    
    return org

@router.get("/{org_id}/members")
async def list_members(
    org_id: int,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user)
):
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    membership = await session.exec(
        select(Membership).where(
            and_(
                Membership.org_id == org_id,
                Membership.user_id == user.id
            )
        )
    )
    
    if not membership.first():
        raise HTTPException(status_code=403, detail="Access denied")
    
    result = await session.exec(
        select(Membership, User)
        .join(User)
        .where(Membership.org_id == org_id)
    )
    
    members = []
    for membership, member_user in result.all():
        members.append({
            "user_id": member_user.id,
            "email": member_user.email,
            "full_name": member_user.full_name,
            "avatar_url": member_user.avatar_url,
            "role": membership.role,
            "joined_at": membership.created_at
        })
    
    return {"members": members}

@router.post("/{org_id}/members")
async def invite_member(
    org_id: int,
    email: str,
    role: str = "member",
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user)
):
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    if role not in ["member", "admin"]:
        raise HTTPException(status_code=400, detail="Invalid role")
    
    membership = await session.exec(
        select(Membership).where(
            and_(
                Membership.org_id == org_id,
                Membership.user_id == user.id,
                Membership.role.in_(["owner", "admin"])
            )
        )
    )
    
    if not membership.first():
        raise HTTPException(status_code=403, detail="Access denied")
    
    existing_user = await session.exec(
        select(User).where(User.email == email)
    )
    invited_user = existing_user.first()
    
    if invited_user:
        existing_membership = await session.exec(
            select(Membership).where(
                and_(
                    Membership.org_id == org_id,
                    Membership.user_id == invited_user.id
                )
            )
        )
        
        if existing_membership.first():
            raise HTTPException(status_code=400, detail="User is already a member")

        await _enforce_team_member_limit(session, org_id)
        
        new_membership = Membership(
            org_id=org_id,
            user_id=invited_user.id,
            role=role
        )
        session.add(new_membership)
        await session.commit()
        
        return {"status": "added", "user_id": invited_user.id}
    else:
        return {"status": "invited", "email": email}

@router.delete("/{org_id}/members/{member_id}")
async def remove_member(
    org_id: int,
    member_id: int,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user)
):
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    user_membership = await session.exec(
        select(Membership).where(
            and_(
                Membership.org_id == org_id,
                Membership.user_id == user.id
            )
        )
    )
    current_membership = user_membership.first()
    
    if not current_membership:
        raise HTTPException(status_code=403, detail="Access denied")
    
    if member_id == user.id and current_membership.role == "owner":
        raise HTTPException(status_code=400, detail="Cannot remove yourself as owner")
    
    if member_id != user.id and current_membership.role not in ["owner", "admin"]:
        raise HTTPException(status_code=403, detail="Access denied")
    
    target_membership = await session.exec(
        select(Membership).where(
            and_(
                Membership.org_id == org_id,
                Membership.user_id == member_id
            )
        )
    )
    target = target_membership.first()
    
    if not target:
        raise HTTPException(status_code=404, detail="Member not found")
    
    if target.role == "owner" and current_membership.role != "owner":
        raise HTTPException(status_code=403, detail="Cannot remove owner")
    
    await session.delete(target)
    await session.commit()
    
    return {"status": "removed"}
