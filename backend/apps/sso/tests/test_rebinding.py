"""Task 8.4 (spec 7.2, 7.4; the limit phase 6 left, D72): the provider's address is checked where the connection
actually goes, not only when its name is first resolved. Between the two a name can be made to resolve to an
internal address ("DNS rebinding"); a local server stands in for that internal address here."""

import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
import requests

from apps.sso import login, services


class _Answer(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 - the handler's name
        self._json()

    def do_POST(self):  # noqa: N802
        self._json()

    def _json(self):
        body = b'{"issuer": "x", "access_token": "t", "token_type": "Bearer"}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture
def internal():
    """A server on this machine's loopback address: what a rebound name would lead to."""
    server = HTTPServer(("127.0.0.1", 0), _Answer)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


@pytest.fixture
def name_checked_as_public(monkeypatch, settings):
    """The name resolved to a public address when it was checked; the connection then goes elsewhere."""
    settings.SSO_ALLOW_PRIVATE_ADDRESSES = False
    monkeypatch.setattr(services, "check_url", lambda url: None)


def test_reading_from_the_provider_refuses_a_connection_that_reached_an_internal_address(
    internal, name_checked_as_public
):
    with pytest.raises(requests.ConnectionError):
        services.fetch_json(f"{internal}/.well-known/openid-configuration")


def test_the_client_secret_is_never_sent_to_an_internal_address(internal, name_checked_as_public, monkeypatch):
    monkeypatch.setenv("AUTHLIB_INSECURE_TRANSPORT", "1")  # the stand-in speaks plain HTTP

    class Config:
        client_id, client_secret = "harak", "the-secret"

    with pytest.raises(requests.ConnectionError):
        login.exchange_code({"token_endpoint": f"{internal}/token"}, Config(), "code", "verifier", "https://h/cb")


def test_a_local_test_provider_is_still_reached_where_the_settings_allow_it(internal, settings):
    settings.SSO_ALLOW_PRIVATE_ADDRESSES = True
    assert services.public_session().get(internal, timeout=5).status_code == 200
