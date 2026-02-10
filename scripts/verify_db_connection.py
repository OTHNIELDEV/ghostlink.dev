import asyncio
import os
import sys
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

async def verify_connection():
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print("❌ Error: DATABASE_URL not found in environment.")
        print("   Please ensure .env file exists and contains DATABASE_URL.")
        return False

    print(f"🔄 Attempting to connect to: {database_url.split('@')[-1] if '@' in database_url else 'local/sqlite'}...")
    
    try:
        engine = create_async_engine(database_url, echo=False)
        async with engine.connect() as conn:
            result = await conn.execute(text("SELECT 1"))
            print("✅ Connection successful!")
            print(f"   Test Query Result: {result.scalar()}")
        await engine.dispose()
        return True
    except Exception as e:
        print(f"❌ Connection failed: {e}")
        return False

if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        
    try:
        success = asyncio.run(verify_connection())
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\nOperation cancelled.")
        sys.exit(130)
