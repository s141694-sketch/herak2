import pytest
from rest_framework.test import APIClient


@pytest.mark.django_db
def test_health_reports_database_and_cache():
    response = APIClient().get("/api/health/")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "checks": {"database": "ok", "redis": "ok"}}


def test_health_is_public_and_json_only():
    response = APIClient().get("/api/health/", HTTP_ACCEPT="text/html")
    assert response.status_code in (200, 503)
    assert response["Content-Type"].startswith("application/json")
