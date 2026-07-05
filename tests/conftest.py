import os
import tempfile
from pathlib import Path

os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{Path(tempfile.gettempdir()) / 'wikingerbot_test.db'}"

import pytest_asyncio  # noqa: E402

import db.models  # noqa: E402,F401 (registriert alle Modelle bei Base.metadata)
from db.base import Base  # noqa: E402
from db.session import async_session_maker, engine  # noqa: E402


@pytest_asyncio.fixture(autouse=True)
async def _reset_schema():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield


@pytest_asyncio.fixture
async def db_session():
    async with async_session_maker() as session:
        yield session
