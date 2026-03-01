"""
Async MongoDB connection using Motor – mirrors src/config/database.ts (Mongoose).

Requires:
  - motor, pymongo
  - dnspython          (for mongodb+srv:// SRV DNS resolution)
  - certifi            (for Atlas TLS CA bundle)
"""
import asyncio
import os
from urllib.parse import urlparse

import certifi
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

_client: AsyncIOMotorClient | None = None
_db: AsyncIOMotorDatabase | None = None

# Retry settings for first connection (Render cold‑start can be slow)
_MAX_RETRIES = 3
_RETRY_DELAY_S = 2


async def connect_db() -> None:
    global _client, _db

    mongo_uri = os.getenv(
        "MONGODB_URI", "mongodb://localhost:27017/resume_builder"
    )
    # Mask credentials in log output
    print(f"Connecting to MongoDB... (uri starts with {mongo_uri[:25]}...)")

    # Use certifi CA bundle so MongoDB Atlas TLS works on all platforms.
    # serverSelectionTimeoutMS keeps startup from hanging forever.
    _client = AsyncIOMotorClient(
        mongo_uri,
        tlsCAFile=certifi.where(),
        serverSelectionTimeoutMS=10_000,
    )

    # Derive the database name from the URI path (e.g. /resume_builder_db)
    parsed = urlparse(mongo_uri)
    db_name = parsed.path.lstrip("/").split("?")[0] or "resume_builder"

    # Ping with retries – transient DNS / TLS errors are common on
    # Render’s free tier during cold starts.
    last_err: Exception | None = None
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            await _client.admin.command("ping")
            _db = _client[db_name]
            print(f"MongoDB connected successfully (attempt {attempt})")
            return
        except Exception as exc:
            last_err = exc
            print(f"MongoDB ping attempt {attempt}/{_MAX_RETRIES} failed: {exc}")
            if attempt < _MAX_RETRIES:
                await asyncio.sleep(_RETRY_DELAY_S)

    # All retries exhausted – raise so lifespan logs the traceback
    raise RuntimeError(
        f"Could not connect to MongoDB after {_MAX_RETRIES} attempts: {last_err}"
    )


async def disconnect_db() -> None:
    global _client
    if _client:
        _client.close()
        print("MongoDB connection closed")


async def ensure_db() -> AsyncIOMotorDatabase:
    """Return the database handle, reconnecting lazily if needed.

    On Render free-tier the startup connection often fails due to transient
    TLS / network errors during cold-start.  Instead of staying broken for
    the whole process lifetime, this helper retries the connection on every
    request that needs the DB until it succeeds.
    """
    global _db
    if _db is not None:
        return _db
    # Attempt a (re-)connection
    await connect_db()
    if _db is None:
        raise RuntimeError("Database not initialised – connect_db() did not set _db")
    return _db


def get_db() -> AsyncIOMotorDatabase:
    """Synchronous accessor – kept for backward compat but prefer ensure_db()."""
    if _db is None:
        raise RuntimeError("Database not initialised – call connect_db() first")
    return _db
