import asyncio
import logging
import sys
import os

# Add project root to sys.path to allow imports from app
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.engine import init_db
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def main():
    load_dotenv()
    database_url = os.getenv("DATABASE_URL")
    
    if not database_url:
        logger.error("DATABASE_URL not found in environment.")
        return
        
    is_sqlite = "sqlite" in database_url
    db_type = "SQLite" if is_sqlite else "PostgreSQL"
    
    logger.info(f"🚀 Initializing {db_type} database...")
    logger.info(f"   URL: {database_url.split('@')[-1] if '@' in database_url else 'local'}")
    
    try:
        await init_db()
        logger.info("✅ Database schema initialized successfully.")
    except Exception as e:
        logger.error(f"❌ Failed to initialize database: {e}")
        sys.exit(1)

if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Operation cancelled.")
