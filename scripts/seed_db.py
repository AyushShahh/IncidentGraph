"""Database verification script for Stage 1."""
import asyncio
from sqlalchemy import text
from backend.db.session import engine


async def verify_db() -> None:
    print("Connecting to PostgreSQL and checking connectivity...")
    async with engine.connect() as conn:
        result = await conn.execute(text("SELECT 1"))
        print(f"Database response: {result.scalar()}")
    print("Database connectivity verified.")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(verify_db())
