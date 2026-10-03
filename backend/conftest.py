import pytest
from django.core.cache import cache


@pytest.fixture(autouse=True)
def clear_cache():
    """Redis persists between runs; throttle counters and health keys must not leak across tests."""
    cache.clear()
    yield
    cache.clear()


@pytest.fixture(autouse=True)
def no_real_collab_service(monkeypatch):
    """Tests never reach a collaboration service that may be running locally; tests that care replace this."""
    from apps.collab import client

    def offline(action, document):
        return {"status": "not_loaded"} if action == "flush" else {"status": "locked"}

    monkeypatch.setattr(client, "call", offline)
