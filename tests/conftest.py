from pathlib import Path

import pytest

from settings import Settings, get_settings

TESTS_DIR = Path(__file__).parent

_DIR_MARKERS = {"unit": "unit", "integration": "integration", "e2e": "e2e"}

def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        path = Path(item.fspath)
        if path.is_relative_to(TESTS_DIR):
            top = path.relative_to(TESTS_DIR).parts[0]
            if top in _DIR_MARKERS:
                item.add_marker(_DIR_MARKERS[top])
        else:
            item.add_marker("eval")


@pytest.fixture(scope="session")
def settings() -> Settings:
    return get_settings()

def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    # Suites for later phases (eval, e2e) are wired into CI before they have
    # tests. "No tests collected" is a pass, not a failure, until they fill in.
    if exitstatus == pytest.ExitCode.NO_TESTS_COLLECTED:
        session.exitstatus = pytest.ExitCode.OK
