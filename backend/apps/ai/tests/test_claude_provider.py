"""The Claude provider sends structured-output requests with the default refusal fallback and maps the SDK's
errors to the gateway's (task 4.4). The SDK client is replaced; no request leaves the machine."""

from types import SimpleNamespace

import anthropic
import httpx2
import pytest

from apps.ai import providers

REQUEST = providers.ProviderRequest(
    system="صنّف الهدف.", user="<data>{}</data>", schema={"type": "object"}, max_tokens=4000, effort="medium"
)


class FakeClient:
    def __init__(self, outcome):
        self.calls = []
        self.outcome = outcome
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return self.outcome


def message(text='{"ok": true}', stop_reason="end_turn", stop_details=None, model="claude-opus-5-5"):
    usage = SimpleNamespace(
        input_tokens=120, output_tokens=30, cache_read_input_tokens=80, cache_creation_input_tokens=0
    )
    return SimpleNamespace(
        content=[SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=text)],
        model=model,
        stop_reason=stop_reason,
        stop_details=stop_details,
        usage=usage,
    )


def test_the_request_asks_for_json_with_effort_caching_and_the_default_fallback():
    client = FakeClient(message())
    response = providers.ClaudeProvider(model="claude-opus-5-5", client=client).complete(REQUEST)
    [kwargs] = client.calls
    assert kwargs["model"] == "claude-opus-5-5" and kwargs["max_tokens"] == 4000
    assert kwargs["betas"] == ["server-side-fallback-2026-07-01"] and kwargs["fallbacks"] == "default"
    assert kwargs["output_config"] == {
        "effort": "medium",
        "format": {"type": "json_schema", "schema": {"type": "object"}},
    }
    assert kwargs["system"] == [{"type": "text", "text": "صنّف الهدف.", "cache_control": {"type": "ephemeral"}}]
    assert kwargs["messages"] == [{"role": "user", "content": "<data>{}</data>"}]
    assert "temperature" not in kwargs and "thinking" not in kwargs
    assert (response.text, response.input_tokens, response.output_tokens, response.cache_read_tokens) == (
        '{"ok": true}',
        120,
        30,
        80,
    )


def test_a_refusal_is_reported_as_such():
    client = FakeClient(message(text="", stop_reason="refusal", stop_details=SimpleNamespace(category="cyber")))
    with pytest.raises(providers.ProviderRefused, match="cyber"):
        providers.ClaudeProvider(model="claude-opus-5-5", client=client).complete(REQUEST)


def _status(cls, code):
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    return cls("failed", response=httpx2.Response(code, request=request), body=None)


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (
            anthropic.APITimeoutError(request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages")),
            providers.ProviderTimeout,
        ),
        (_status(anthropic.RateLimitError, 429), providers.ProviderTransient),
        (_status(anthropic.InternalServerError, 500), providers.ProviderTransient),
        (_status(anthropic.BadRequestError, 400), providers.ProviderError),
        (_status(anthropic.AuthenticationError, 401), providers.ProviderError),
    ],
)
def test_sdk_errors_map_to_retryable_or_final(error, expected):
    provider = providers.ClaudeProvider(model="claude-opus-5-5", client=FakeClient(error))
    with pytest.raises(expected) as raised:
        provider.complete(REQUEST)
    assert type(raised.value) is expected


# Structured outputs accept a subset of JSON Schema: string lengths, numeric bounds and array sizes above one are not
# supported (platform.claude.com/docs/en/build-with-claude/structured-outputs). The provider sends the supported part
# and states the rest in descriptions; the gateway still validates every answer against the full schema.
UNSUPPORTED = {
    "minLength",
    "maxLength",
    "pattern",
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "multipleOf",
    "maxItems",
    "uniqueItems",
    "minProperties",
    "maxProperties",
}


def _keys(schema):
    if isinstance(schema, dict):
        for key, value in schema.items():
            if key not in ("properties", "$defs"):
                yield key, value
            yield from _keys(value) if key not in ("enum", "const") else ()
    elif isinstance(schema, list):
        for value in schema:
            yield from _keys(value)


def _unsupported(schema):
    return sorted(
        {key for key, value in _keys(schema) if key in UNSUPPORTED or (key == "minItems" and value not in (0, 1))}
    )


def test_only_supported_schema_keywords_are_sent_and_the_rest_is_described():
    schema = {
        "type": "object",
        "properties": {
            "text": {"type": "string", "minLength": 8, "maxLength": 400, "description": "The objective."},
            "items": {"type": "array", "minItems": 2, "maxItems": 30, "items": {"type": "string", "maxLength": 9}},
            "level": {"type": "integer", "minimum": 0, "maximum": 7},
            "kind": {"type": "string", "enum": ["a", "b"]},
        },
        "required": ["text", "items", "level", "kind"],
        "additionalProperties": False,
    }
    client = FakeClient(message())
    providers.ClaudeProvider(model="claude-opus-5-5", client=client).complete(
        providers.ProviderRequest(system="s", user="u", schema=schema, max_tokens=100, effort="low")
    )
    sent = client.calls[0]["output_config"]["format"]["schema"]
    assert _unsupported(sent) == []
    text = sent["properties"]["text"]
    assert text["type"] == "string" and "8" in text["description"] and "400" in text["description"]
    assert text["description"].startswith("The objective.")
    assert "30" in sent["properties"]["items"]["description"] and "minItems" not in sent["properties"]["items"]
    assert sent["properties"]["kind"] == {"type": "string", "enum": ["a", "b"]}
    assert sent["additionalProperties"] is False and sent["required"] == ["text", "items", "level", "kind"]
    assert schema["properties"]["text"]["maxLength"] == 400, "the agent's own schema is left whole"


def test_every_agent_schema_reaches_the_api_in_its_supported_form():
    from apps.evals.evaluation import REGISTRY

    assert REGISTRY
    for agent in REGISTRY.values():
        assert _unsupported(providers.wire_schema(agent.spec.schema)) == [], agent.name
