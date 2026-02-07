#!/usr/bin/env python3
"""
테스트 데이터 초기화 스크립트
조직, 사용자, 사이트, 구독 정보를 생성합니다.
"""
import asyncio
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession
from app.db.engine import engine, init_db
from app.models.user import User
from app.models.organization import Organization, Membership
from app.models.site import Site
from app.models.billing import Subscription, SubscriptionStatus
from app.core.security import get_password_hash
from datetime import datetime, timedelta



async def create_test_data():
    """테스트 데이터 생성"""
    await init_db()
    
    async with AsyncSession(engine) as session:
        # 1. 테스트 사용자 생성
        print("📝 테스트 사용자 생성 중...")
        
        # 기존 사용자 확인
        result = await session.exec(select(User).where(User.email == "test@ghostlink.io"))
        existing_user = result.first()
        
        if existing_user:
            print("✅ 기존 테스트 사용자 발견")
            user = existing_user
        else:
            user = User(
                email="test@ghostlink.io",
                hashed_password=get_password_hash("test1234"),
                full_name="Test User",
                is_active=True,
                is_verified=True
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)
            print(f"✅ 사용자 생성 완료: {user.email}")
        
        # 2. 조직 생성
        print("\n🏢 조직 생성 중...")
        result = await session.exec(select(Organization).where(Organization.slug == "test-org"))
        existing_org = result.first()
        
        user_id = user.id  # ID를 미리 저장하여 lazy loading 문제 방지
        
        if existing_org:
            print("✅ 기존 조직 발견")
            org = existing_org
        else:
            org = Organization(
                name="Test Organization",
                slug="test-org"
            )
            session.add(org)
            await session.commit()
            await session.refresh(org)
            print(f"✅ 조직 생성 완료: {org.name}")
        
        org_id = org.id  # ID를 미리 저장
        
        # 3. 멤버십 생성
        print("\n👥 멤버십 생성 중...")
        result = await session.exec(
            select(Membership).where(
                Membership.user_id == user_id,
                Membership.org_id == org_id
            )
        )
        existing_membership = result.first()
        
        if not existing_membership:
            membership = Membership(
                user_id=user_id,
                org_id=org_id,
                role="owner"
            )
            session.add(membership)
            await session.commit()
            print("✅ 멤버십 생성 완료")
        else:
            print("✅ 기존 멤버십 발견")
        
        # 4. 구독 생성 (Free 플랜)
        print("\n💳 구독 생성 중...")
        result = await session.exec(
            select(Subscription).where(Subscription.org_id == org_id)
        )
        existing_sub = result.first()
        
        if not existing_sub:
            subscription = Subscription(
                org_id=org_id,
                plan_code="free",
                status=SubscriptionStatus.ACTIVE,
                current_period_start=datetime.utcnow(),
                current_period_end=datetime.utcnow() + timedelta(days=30)
            )
            session.add(subscription)
            await session.commit()
            print("✅ Free 플랜 구독 생성 완료")
        else:
            print(f"✅ 기존 구독 발견: {existing_sub.plan_code}")
        
        # 5. 샘플 사이트 생성
        print("\n🌐 샘플 사이트 생성 중...")
        result = await session.exec(
            select(Site).where(
                Site.org_id == org_id,
                Site.url == "https://example.com"
            )
        )
        existing_site = result.first()
        
        if not existing_site:
            site = Site(
                url="https://example.com",
                org_id=org_id,
                owner_id=user_id,
                status="completed",
                schema_type="Organization",
                json_ld_content='{"@context":"https://schema.org","@type":"Organization","name":"Example Corp"}',
                llms_txt_content="# Example Corp\\n\\nA sample organization for testing.",
                seo_description="Example organization for testing GhostLink",
                ai_score=85,
                last_scanned_at=datetime.utcnow()
            )
            session.add(site)
            await session.commit()
            print("✅ 샘플 사이트 생성 완료")
        else:
            print("✅ 기존 샘플 사이트 발견")
        
        print("\n" + "="*60)
        print("🎉 테스트 데이터 초기화 완료!")
        print("="*60)
        print(f"\n📧 이메일: test@ghostlink.io")
        print(f"🔑 비밀번호: test1234")
        print(f"🏢 조직: {org.name}")
        print(f"🌐 사이트: https://example.com")
        print(f"\n💡 http://localhost:8000 에서 로그인하세요!")
        print("="*60)


if __name__ == "__main__":
    asyncio.run(create_test_data())
