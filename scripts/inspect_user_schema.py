import asyncio
import os
import sys
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine
from dotenv import load_dotenv

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

load_dotenv()

async def inspect_schema():
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print("DATABASE_URL not found")
        return

    connect_args = {}
    if "postgresql" in database_url:
        connect_args["statement_cache_size"] = 0

    engine = create_async_engine(database_url, echo=False, connect_args=connect_args)
    
    async with engine.connect() as conn:
        def get_columns(sync_conn):
            inspector = inspect(sync_conn)
            return inspector.get_columns("user")
            
        columns = await conn.run_sync(get_columns)
        print("Columns in 'user' table:")
        found = False
        for col in columns:
            print(f"- {col['name']} ({col['type']})")
            if col['name'] == 'preferred_ui_language':
                found = True
        
        if found:
            print("\n✅ 'preferred_ui_language' column FOUND.")
        else:
            print("\n❌ 'preferred_ui_language' column NOT FOUND.")

if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(inspect_schema())
