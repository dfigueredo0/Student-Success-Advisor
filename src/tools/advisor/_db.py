"""Shared SQLAlchemy engine for advisor tools that read the catalog tables."""

from functools import lru_cache

from sqlalchemy import Engine, create_engine

from settings import get_settings

@lru_cache
def engine() -> Engine:
    return create_engine(get_settings().database_url, pool_pre_ping=True)
