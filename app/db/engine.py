from sqlmodel import create_engine
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import inspect, text
from app.core.config import settings

engine = create_async_engine(
    settings.DATABASE_URL, 
    echo=settings.ENVIRONMENT == "development",
    future=True
)

async def get_session() -> AsyncSession:
    async_session = sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    async with async_session() as session:
        yield session

async def init_db():
    from sqlmodel import SQLModel
    from app.models import user
    from app.models import site
    from app.models import analytics
    from app.models import organization
    from app.models import billing
    from app.models import api_key
    from app.models import webhook_event
    from app.models import optimization
    from app.models import approval
    from app.models import audit_log
    from app.models import innovation
    from app.models import innovation_plus
    
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
        await conn.run_sync(_ensure_site_columns)


def _ensure_site_columns(sync_conn):
    inspector = inspect(sync_conn)
    if "site" not in inspector.get_table_names():
        return

    existing = {col["name"] for col in inspector.get_columns("site")}
    additions = {
        "title": "VARCHAR",
        "meta_description": "VARCHAR",
        "json_ld": "TEXT",
        "llms_txt": "TEXT",
    }

    for column_name, column_type in additions.items():
        if column_name in existing:
            continue
        sync_conn.execute(text(f"ALTER TABLE site ADD COLUMN {column_name} {column_type}"))
