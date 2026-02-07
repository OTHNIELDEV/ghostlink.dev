from typing import Iterable, Optional

from fastapi import HTTPException, Request
from sqlmodel import and_, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.organization import Membership, Organization
from app.models.user import User


async def get_request_value(request: Request, key: str) -> str | None:
    value = request.query_params.get(key)
    if value is not None:
        return value

    try:
        form = await request.form()
    except Exception:
        return None

    form_value = form.get(key)
    return str(form_value) if form_value is not None else None


def parse_org_id(org_id_raw: str | None) -> int:
    if not org_id_raw:
        raise HTTPException(status_code=400, detail="Organization ID required")
    try:
        return int(org_id_raw)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid organization ID")


def parse_bool(raw_value: str | None, default: bool = False) -> bool:
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


async def resolve_org_id_from_request(request: Request, key: str = "org_id") -> int:
    return parse_org_id(await get_request_value(request, key))


async def require_org_membership(
    session: AsyncSession,
    user: User,
    org_id: int,
    roles: Optional[Iterable[str]] = None,
) -> Membership:
    query = select(Membership).where(
        and_(
            Membership.org_id == org_id,
            Membership.user_id == user.id,
        )
    )
    if roles:
        query = query.where(Membership.role.in_(list(roles)))

    result = await session.exec(query)
    membership = result.first()
    if not membership:
        raise HTTPException(status_code=403, detail="Access denied")
    return membership


async def require_org_access(
    session: AsyncSession,
    user: User,
    org_id: int,
    roles: Optional[Iterable[str]] = None,
) -> tuple[Organization, Membership]:
    org = await session.get(Organization, org_id)
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")
    membership = await require_org_membership(session, user, org_id, roles=roles)
    return org, membership
