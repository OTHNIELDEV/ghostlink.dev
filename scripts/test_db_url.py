import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
import sys

async def test_engine():
    # Simulate Supabase URL scheme
    url = "postgres://user:pass@host:5432/db"
    print(f"Testing URL: {url}")
    try:
        engine = create_async_engine(url)
        # Just trying to create the engine might not trigger the error until connect is called,
        # but dialect loading happens early.
        async with engine.connect() as conn:
            pass
    except Exception as e:
        print(f"Caught expected error: {e}")
        # Check if it mentions driver
        if "driver" in str(e).lower() or "module" in str(e).lower():
            print("CONFIRMED: Missing driver specification causes error.")
            sys.exit(0)
        else:
            print(f"Other error: {e}")
            # If it's a connection error (nodename nor servname provided...), that means it TRIED to connect
            # which means the scheme was accepted.
            if "nodename nor servname" in str(e) or "connection refused" in str(e):
                 print("Scheme accepted, but connection failed (expected).")
                 sys.exit(1)

    print("Success?")

if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    try:
        asyncio.run(test_engine())
    except Exception as e:
        print(f"Top level error: {e}")
