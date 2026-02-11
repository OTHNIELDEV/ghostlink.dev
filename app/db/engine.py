from uuid import uuid4

from sqlalchemy import inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings


def _is_postgres_url(database_url: str) -> bool:
    return database_url.startswith("postgresql") or database_url.startswith("postgres")


db_url = settings.DATABASE_URL
db_url_obj = make_url(db_url)
connect_args: dict = {}
engine_kwargs: dict = {
    "echo": settings.ENVIRONMENT == "development",
    "future": True,
}

if _is_postgres_url(db_url):
    # Prevent prepared statement collisions with asyncpg + PgBouncer transaction mode.
    connect_args["statement_cache_size"] = 0
    connect_args["prepared_statement_cache_size"] = 0
    connect_args["prepared_statement_name_func"] = lambda: f"__asyncpg_{uuid4()}__"

    # For Supabase pooler (6543), avoid SQLAlchemy connection reuse.
    if db_url_obj.port == 6543:
        engine_kwargs["poolclass"] = NullPool

    if settings.ENVIRONMENT == "production":
        connect_args.setdefault("ssl", "require")

engine = create_async_engine(
    db_url,
    connect_args=connect_args,
    **engine_kwargs,
)

async_session_factory = sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

import time
import logging

logger = logging.getLogger(__name__)

async def get_session() -> AsyncSession:
    start_time = time.time()
    async with async_session_factory() as session:
        yield session
        
    duration = time.time() - start_time
    if duration > 0.2:
         logger.warning(f"Slow DB Session: {duration:.4f}s")

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
        await conn.run_sync(_ensure_optimization_columns)
        await conn.run_sync(_ensure_bandit_columns)
        await conn.run_sync(_ensure_approval_columns)


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


def _ensure_optimization_columns(sync_conn):
    inspector = inspect(sync_conn)
    if "optimizationaction" not in inspector.get_table_names():
        return

    existing = {col["name"] for col in inspector.get_columns("optimizationaction")}
    additions = {
        "source_recommendation": "TEXT",
        "rationale": "TEXT",
        "status": "VARCHAR DEFAULT 'pending'",
        "loop_version": "VARCHAR DEFAULT 'v1'",
        "decided_by_user_id": "INTEGER",
        "applied_by_user_id": "INTEGER",
        "decided_at": "TIMESTAMP",
        "applied_at": "TIMESTAMP",
        "error_msg": "TEXT",
        "created_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
        "updated_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
    }

    for column_name, column_type in additions.items():
        if column_name in existing:
            continue
        sync_conn.execute(
            text(f"ALTER TABLE optimizationaction ADD COLUMN {column_name} {column_type}")
        )


def _ensure_bandit_columns(sync_conn):
    inspector = inspect(sync_conn)

    if "optimizationbanditarm" in inspector.get_table_names():
        arm_existing = {col["name"] for col in inspector.get_columns("optimizationbanditarm")}
        arm_additions = {
            "alpha": "FLOAT DEFAULT 1.0",
            "beta": "FLOAT DEFAULT 1.0",
            "pulls": "INTEGER DEFAULT 0",
            "cumulative_reward": "FLOAT DEFAULT 0.0",
            "average_reward": "FLOAT DEFAULT 0.0",
            "last_reward": "FLOAT",
            "last_reward_at": "TIMESTAMP",
            "metadata_json": "TEXT DEFAULT '{}'",
            "created_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
            "updated_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
        }
        for column_name, column_type in arm_additions.items():
            if column_name in arm_existing:
                continue
            sync_conn.execute(
                text(f"ALTER TABLE optimizationbanditarm ADD COLUMN {column_name} {column_type}")
            )

    if "optimizationbanditdecision" in inspector.get_table_names():
        decision_existing = {col["name"] for col in inspector.get_columns("optimizationbanditdecision")}
        decision_additions = {
            "selected_action_id": "INTEGER",
            "selected_arm_key": "VARCHAR",
            "strategy": "VARCHAR DEFAULT 'thompson'",
            "scored_candidates_json": "TEXT DEFAULT '[]'",
            "context_json": "TEXT DEFAULT '{}'",
            "created_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
        }
        for column_name, column_type in decision_additions.items():
            if column_name in decision_existing:
                continue
            sync_conn.execute(
                text(f"ALTER TABLE optimizationbanditdecision ADD COLUMN {column_name} {column_type}")
            )


def _ensure_approval_columns(sync_conn):
    inspector = inspect(sync_conn)
    if "approvalrequest" not in inspector.get_table_names():
        return

    existing = {col["name"] for col in inspector.get_columns("approvalrequest")}
    additions = {
        "reviewed_by_user_id": "INTEGER",
        "requester_note": "TEXT",
        "review_note": "TEXT",
        "execution_result": "TEXT",
        "reviewed_at": "TIMESTAMP",
        "updated_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
    }

    for column_name, column_type in additions.items():
        if column_name in existing:
            continue
        sync_conn.execute(
            text(f"ALTER TABLE approvalrequest ADD COLUMN {column_name} {column_type}")
        )
