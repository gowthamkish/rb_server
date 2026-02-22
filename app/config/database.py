"""
Async MongoDB connection using Motor – mirrors src/config/database.ts (Mongoose).
"""
import os
from urllib.parse import urlparse

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

_client: AsyncIOMotorClient | None = None
_db: AsyncIOMotorDatabase | None = None


async def connect_db() -> None:
    global _client, _db

    mongo_uri = os.getenv(
        "MONGODB_URI", "mongodb://localhost:27017/resume_builder"
    )
    print(f"Connecting to MongoDB... {mongo_uri}")

    _client = AsyncIOMotorClient(mongo_uri)

    # Derive the database name from the URI path (e.g. /resume_builder_db)
    parsed = urlparse(mongo_uri)
    db_name = parsed.path.lstrip("/").split("?")[0] or "resume_builder"
    _db = _client[db_name]

    # Ping to verify the connection
    await _client.admin.command("ping")
    print("MongoDB connected successfully")


async def disconnect_db() -> None:
    global _client
    if _client:
        _client.close()
        print("MongoDB connection closed")


def get_db() -> AsyncIOMotorDatabase:
    if _db is None:
        raise RuntimeError("Database not initialised – call connect_db() first")
    return _db
