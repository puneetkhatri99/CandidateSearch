"""Database engine, session factory, and the declarative base for all ORM models."""

import importlib
import importlib.util
import pkgutil
import uuid
from collections.abc import AsyncIterator
from datetime import datetime
from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from sqlalchemy import DateTime, MetaData, func
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.core.config import get_settings

# Deterministic constraint names keep Alembic autogenerate diffs stable.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class TimestampedModel(Base):
    """Base for every table: UUID primary key plus created/updated timestamps."""

    __abstract__ = True

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


def register_all_models() -> None:
    """Import every features/<name>/models.py so cross-table foreign keys can resolve.

    A process that loads only one feature (the embedding worker or a CLI command) would
    otherwise fail on the first insert with NoReferencedTableError. Modules are found by name,
    so core never depends on features at import time.
    """
    spec = importlib.util.find_spec("app.features")
    for feature in pkgutil.iter_modules(spec.submodule_search_locations if spec else None):
        if feature.ispkg and importlib.util.find_spec(f"app.features.{feature.name}.models"):
            importlib.import_module(f"app.features.{feature.name}.models")
    # The one table core owns (core/rate_limit.py); imported lazily because it imports this module.
    importlib.import_module("app.core.rate_limit")


@lru_cache
def get_engine() -> AsyncEngine:
    settings = get_settings()
    return create_async_engine(
        str(settings.database_url),
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_pre_ping=True,
        echo=settings.db_echo,
    )


@lru_cache
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with get_sessionmaker()() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_session)]
