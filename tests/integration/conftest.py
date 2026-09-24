from collections.abc import Iterator

import httpx
import pytest
from sqlalchemy import Engine, create_engine

from settings import Settings

@pytest.fixture(scope="session")
def engine(settings: Settings) -> Iterator[Engine]:
    eng = create_engine(settings.database_url, pool_pre_ping=True)
    yield eng
    eng.dispose()

@pytest.fixture(scope="session")
def langfuse(settings: Settings) -> Iterator[httpx.Client]:
    auth = (settings.langfuse_public_key, settings.langfuse_secret_key.get_secret_value())
    with httpx.Client(base_url=settings.langfuse_host, auth=auth, timeout=30) as c:
        yield c
