
import asyncio
import os
import logging
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel, create_engine, select
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlalchemy import inspect, text

# Import all models to ensure they are registered in SQLModel.metadata
from app.models import (
    user, site, analytics, organization, billing, api_key, 
    webhook_event, optimization, approval, audit_log, 
    innovation, innovation_plus
    # Add other models as needed
)

# Configure Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# --- Configuration ---
# 1. Source DB (Read from Environment)
from dotenv import load_dotenv
load_dotenv()
SOURCE_DB_URL = os.getenv("DATABASE_URL")

# 2. Destination DB (Provided by User)
# NOTE: User provided: postgresql://...
# We must convert to postgresql+asyncpg:// for SQLAlchemy async engine
RAW_DEST_DB_URL = "postgresql://postgres.kkossoaplpygcslwtkym:ogKJyZv7RInZ2591@aws-1-ap-northeast-2.pooler.supabase.com:6543/postgres?pgbouncer=true"

def fix_db_url(url: str) -> str:
    if "pgbouncer=true" in url:
        url = url.replace("?pgbouncer=true", "").replace("&pgbouncer=true", "")
    
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+asyncpg://", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url

SOURCE_DB_URL = fix_db_url(SOURCE_DB_URL)
DEST_DB_URL = fix_db_url(RAW_DEST_DB_URL)

logger.info(f"Source DB: {SOURCE_DB_URL.split('@')[-1]}") # Log only host part for safety
logger.info(f"Dest DB:   {DEST_DB_URL.split('@')[-1]}")

import uuid

async def migrate():
    # Create Engines
    # Apply robust settings to BOTH Source and Dest if they are Transaction Poolers (6543)
    # Since we know Source is also 6543 from .env, we apply it there too.
    
    robust_connect_args = {
        "statement_cache_size": 0,
        "prepared_statement_cache_size": 0,
        "prepared_statement_name_func": lambda: f"__asyncpg_{uuid.uuid4()}__"
    }

    source_engine = create_async_engine(
        SOURCE_DB_URL, 
        echo=False,
        connect_args=robust_connect_args
    )
    
    # Supabase Transaction Mode (6543) requires disabling all caching
    dest_engine = create_async_engine(
        DEST_DB_URL, 
        echo=False,
        connect_args=robust_connect_args
    )

    logger.info("Testing connections...")
    async with source_engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
    logger.info("Source connection OK.")

    async with dest_engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
    logger.info("Destination connection OK.")

    # 1. Create Schema in Destination
    logger.info("Creating schema in Destination DB...")
    async with dest_engine.begin() as conn:
        # await conn.run_sync(SQLModel.metadata.drop_all) # Optional: Wipe dest if needed? Better safe than sorry, let's append/upsert or just create if not exists.
        # User said "newly created DB", so it should be empty.
        await conn.run_sync(SQLModel.metadata.create_all)
    logger.info("Schema created.")

    # 2. Migrate Data Table by Table
    # We must respect foreign key order.
    # SQLModel.metadata.sorted_tables gives a topologically sorted list.
    tables = SQLModel.metadata.sorted_tables
    
    async with AsyncSession(source_engine) as source_session, AsyncSession(dest_engine) as dest_session:
        for table in tables:
            table_name = table.name
            logger.info(f"Migrating table: {table_name}...")
            
            # Fetch all rows from Source
            # We use text() query for raw table access to avoid model-level validation issues during transport
            # But converting to Model objects is easier for insert if models match.
            # Let's try raw select to keep it generic and model-agnostic if possible, 
            # BUT SQLModel session.add requires model instances. 
            # Given we imported models, let's use the Model class if we can map it.
            # Actually, raw SQL copy is faster and deeper.
            
            # Dynamic Model loading? No, let's stick to raw dictionaries to generic insert.
            
            # Fetch rows
            result = await source_session.execute(table.select())
            rows = result.all()
            
            if not rows:
                logger.info(f"  - No rows to migrate for {table_name}.")
                continue
            
            count = len(rows)
            logger.info(f"  - Found {count} rows. Inserting...")
            
            # Convert rows (which are NamedTuples or Row objects) to dicts for Insert statement
            # The result keys match columns.
            
            # Bulk Insert using Core SQLAlchemy to bypass ORM overhead and some validation
            # table.insert().values([...])
            
            batch_size = 1000
            # rows is a list of Row objects. keys via ._mapping
            
            data_list = [dict(row._mapping) for row in rows]
            
            # Chunking
            for i in range(0, count, batch_size):
                batch = data_list[i : i + batch_size]
                # Use core insert
                stmt = table.insert().values(batch)
                # We need to execute on the engine connection or session?
                # Using session.execute with core statement
                await dest_session.execute(stmt)
            
            await dest_session.commit()
            logger.info(f"  - {count} rows committed.")

    logger.info("Migration Complete!")

if __name__ == "__main__":
    asyncio.run(migrate())
