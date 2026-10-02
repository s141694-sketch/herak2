import pytest
from django.core.cache import cache


@pytest.fixture(autouse=True)
def clear_cache():
    """Redis persists between runs; throttle counters and health keys must not leak across tests."""
    cache.clear()
    yield
    cache.clear()
