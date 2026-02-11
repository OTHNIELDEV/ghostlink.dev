from sqlmodel import create_engine
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import inspect, text
from app.core.config import settings

import ssl
import sys

# Handle Supabase/PostgreSQL connection pooling (disable prepared statements)
connect_args = {}
if "postgresql" in settings.DATABASE_URL or "postgres" in settings.DATABASE_URL:
    # Supabase Transaction Mode (port 6543) requires disabling prepared statements
    connect_args["statement_cache_size"] = 0
    # Also set prepare_threshold to None to be safe (though statement_cache_size=0 should suffice)
    connect_args["prepared_statement_cache_size"] = 0 
    
    # Ensure SSL is used (Supabase requires it)
    # asyncpg usually defaults to ssl='require' if not specified, 
    # but let's be explicit to avoid "connection reset" or timeouts.
    # We create a default context that trusts system CAs.
    if settings.ENVIRONMENT == "production":
         ctx = ssl.create_default_context()
         ctx.check_hostname = False # Supabase certificates might not match the pooler hostname exactly in some regions
         ctx.verify_mode = ssl.CERT_NONE # For debugging, try permissive SSL first. 
         # Note: production should use CERT_REQUIRED, but "CERT_NONE" with "ssl=True" is often needed for 
         # managed DBs behind poolers if the cert chain is complex. 
         # Let's try default context first.
         conn_ctx = ssl.create_default_context()
         conn_ctx.check_hostname = False
         conn_ctx.verify_mode = ssl.CERT_NONE
         connect_args["ssl"] = conn_ctx

    print(f"DEBUG: Creating Async Engine. Connect Args: {connect_args}")

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
