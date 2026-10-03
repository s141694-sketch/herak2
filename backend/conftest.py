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

    def offline(action, document, **kwargs):
        if action == "freeze":
            return {"status": "not_loaded", "token": "test"}
        return {"snapshot": {"status": "not_loaded"}, "unfreeze": {"status": "unfrozen"}}.get(
            action, {"status": "locked"}
        )

    monkeypatch.setattr(client, "call", offline)
