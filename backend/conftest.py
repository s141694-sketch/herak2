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


@pytest.fixture(scope="session", autouse=True)
def _files_store():
    """An S3-compatible store for the whole run (moto, in the process): stored files go nowhere else (D75). The test
    settings leave FILES_ENDPOINT_URL empty, so the clients go to moto's stand-in for the cloud."""
    from moto import mock_aws

    from apps.files import storage

    with mock_aws():
        storage._client.cache_clear()  # clients made outside the mock would reach the network
        storage.ensure_bucket()
        yield storage
    storage._client.cache_clear()


@pytest.fixture
def files_storage(_files_store):
    return _files_store
