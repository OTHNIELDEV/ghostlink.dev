from sqlmodel import create_engine
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import inspect, text
from app.core.config import settings

# Handle Supabase/PostgreSQL connection pooling (disable prepared statements)
connect_args = {}
if "postgresql" in settings.DATABASE_URL:
    connect_args["statement_cache_size"] = 0

engine = create_async_engine(
    settings.DATABASE_URL, 
    echo=settings.ENVIRONMENT == "development",
    future=True,
    connect_args=connect_args
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
        await conn.run_sync(_ensure_organization_columns)
        await conn.run_sync(_ensure_user_columns)
        await conn.run_sync(_ensure_analytics_columns)


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
        "preferred_language": "VARCHAR(16) DEFAULT 'auto'",
    }

    for column_name, column_type in additions.items():
        if column_name in existing:
            continue
        sync_conn.execute(text(f"ALTER TABLE site ADD COLUMN {column_name} {column_type}"))


def _ensure_organization_columns(sync_conn):
    inspector = inspect(sync_conn)
    if "organization" not in inspector.get_table_names():
        return

    existing = {col["name"] for col in inspector.get_columns("organization")}
    additions = {
        "preferred_language": "VARCHAR(16) DEFAULT 'auto'",
    }

    for column_name, column_type in additions.items():
        if column_name in existing:
            continue
        sync_conn.execute(text(f"ALTER TABLE organization ADD COLUMN {column_name} {column_type}"))


def _ensure_user_columns(sync_conn):
    inspector = inspect(sync_conn)
    if "user" not in inspector.get_table_names():
        return

    existing = {col["name"] for col in inspector.get_columns("user")}
    additions = {
        "preferred_ui_language": "VARCHAR(16) DEFAULT 'auto'",
    }

    for column_name, column_type in additions.items():
        if column_name in existing:
            continue
        sync_conn.execute(text(f"ALTER TABLE user ADD COLUMN {column_name} {column_type}"))


def _ensure_analytics_columns(sync_conn):
    inspector = inspect(sync_conn)
    if "bridgeeventraw" not in inspector.get_table_names():
        return

    existing = {col["name"] for col in inspector.get_columns("bridgeeventraw")}
    additions = {
        "retry_count": "INTEGER DEFAULT 0",
        "next_retry_at": "DATETIME",
        "last_error": "VARCHAR",
    }

    for column_name, column_type in additions.items():
        if column_name in existing:
            continue
        sync_conn.execute(text(f"ALTER TABLE bridgeeventraw ADD COLUMN {column_name} {column_type}"))
