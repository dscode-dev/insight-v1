from __future__ import annotations

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def build_engine(
    url: str, *, pool_size: int = 5, max_overflow: int = 10, echo: bool = False
) -> AsyncEngine:
    # SQLite (used in tests) doesn't support pooling args the same way.
    kwargs: dict = {"echo": echo}
    if not url.startswith("sqlite"):
        kwargs.update({"pool_size": pool_size, "max_overflow": max_overflow})
    return create_async_engine(url, **kwargs)


def build_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
