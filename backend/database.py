import os
import re
from typing import AsyncGenerator
from dotenv import load_dotenv

# Ensure environment variables from root or backend .env are loaded
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import declarative_base, sessionmaker

def get_async_database_url() -> str:
    raw_url = os.getenv("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/sceptic")
    # Normalize url scheme to postgresql+asyncpg://
    if raw_url.startswith("postgresql://"):
        raw_url = raw_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    elif raw_url.startswith("postgres://"):
        raw_url = raw_url.replace("postgres://", "postgresql+asyncpg://", 1)
    return raw_url

def get_sync_database_url() -> str:
    raw_url = os.getenv("DATABASE_URL", "postgresql+psycopg2://postgres:postgres@localhost:5432/sceptic")
    if raw_url.startswith("postgresql+asyncpg://"):
        raw_url = raw_url.replace("postgresql+asyncpg://", "postgresql+psycopg2://", 1)
    elif raw_url.startswith("postgresql://"):
        raw_url = raw_url.replace("postgresql://", "postgresql+psycopg2://", 1)
    elif raw_url.startswith("postgres://"):
        raw_url = raw_url.replace("postgres://", "postgresql+psycopg2://", 1)
    return raw_url

DATABASE_URL = get_async_database_url()

# Async Engine with connection pooling and pre-ping
# Supabase transaction poolers (pgbouncer on port 6543) require statement_cache_size=0
async_engine = create_async_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
    echo=False,
    connect_args={
        "statement_cache_size": 0,
        "prepared_statement_cache_size": 0,
    },
)

# Async Session Factory
AsyncSessionLocal = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)

Base = declarative_base()

# Sync Engine and SessionLocal for synchronous workers (e.g. Celery worker process)
SYNC_DATABASE_URL = get_sync_database_url()
sync_engine = create_engine(
    SYNC_DATABASE_URL,
    pool_pre_ping=True,
)
SessionLocal = sessionmaker(
    bind=sync_engine,
    autocommit=False,
    autoflush=False,
)

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency yielding an async database session."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
