"""Model providers behind the gateway. This module is the only place that talks to an AI vendor.

A provider takes a system prompt, one user message and a JSON schema, and returns the raw text and
token usage. It knows nothing about organizations, quotas, caching or retries; the gateway does.
"""

import hashlib
import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from django.conf import settings


class ProviderError(Exception):
    """A failure that retrying will not fix (bad request, authentication, missing recording)."""


class ProviderTransient(ProviderError):
    """Rate limit, overload, server error or lost connection: worth another attempt."""


class ProviderTimeout(ProviderTransient):
    pass


class ProviderRefused(ProviderError):
    """The model declined the request. ``response`` carries what the declined attempt cost, when known."""

    def __init__(self, message: str, response: "ProviderResponse | None" = None):
        super().__init__(message)
        self.response = response


@dataclass(frozen=True)
class ProviderRequest:
    system: str
    user: str
    schema: dict
    max_tokens: int
    effort: str


@dataclass(frozen=True)
class ProviderResponse:
    text: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    stop_reason: str = "end_turn"


@dataclass
class ProviderBase:
    model: str
    name: str = field(default="base", init=False)

    def complete(self, request: ProviderRequest) -> ProviderResponse:
        raise NotImplementedError


#: JSON Schema keywords structured outputs do not support (platform.claude.com/docs/en/build-with-claude/
#: structured-outputs: string, numerical and complex array constraints). minItems is supported only as 0 or 1.
_UNSUPPORTED = (
    "minLength",
    "maxLength",
    "pattern",
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "multipleOf",
    "minItems",
    "maxItems",
    "uniqueItems",
    "minProperties",
    "maxProperties",
)


def wire_schema(schema):
    """The schema as the API accepts it: unsupported constraints removed and stated in the description instead,
    as the official SDKs do. The gateway validates every answer against the full schema, so nothing is lost."""
    if isinstance(schema, list):
        return [wire_schema(item) for item in schema]
    if not isinstance(schema, dict):
        return schema
    sent: dict = {}
    constraints: list[str] = []
    for key, value in schema.items():
        if key in ("enum", "const"):
            sent[key] = value
        elif key == "properties" or key == "$defs":
            sent[key] = {name: wire_schema(sub) for name, sub in value.items()}
        elif key == "minItems" and value in (0, 1):
            sent[key] = value
        elif key in _UNSUPPORTED:
            constraints.append(f"{key} {value}")
        else:
            sent[key] = wire_schema(value)
    if constraints:
        note = f"Constraints: {', '.join(constraints)}."
        sent["description"] = f"{sent['description']} {note}" if sent.get("description") else note
    return sent


@dataclass
class ClaudeProvider(ProviderBase):
    """Claude through the official SDK, with structured JSON output.

    No server-side fallback: a declined request is reported as declined. Another model answering would bypass the
    release gate, which opens an agent only for the exact model it was evaluated on (spec 5.5, D49).
    """

    timeout: float = 60.0
    client: object | None = None
    name: str = field(default="claude", init=False)

    def _client(self):
        if self.client is None:
            import anthropic

            # The gateway retries with its own backoff and records every attempt, so the SDK does not retry.
            self.client = anthropic.Anthropic(timeout=self.timeout, max_retries=0)
        return self.client

    def complete(self, request: ProviderRequest) -> ProviderResponse:
        import anthropic

        try:
            response = self._client().beta.messages.create(
                model=self.model,
                max_tokens=request.max_tokens,
                system=[{"type": "text", "text": request.system, "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": request.user}],
                output_config={
                    "effort": request.effort,
                    "format": {"type": "json_schema", "schema": wire_schema(request.schema)},
                },
            )
        except anthropic.APITimeoutError as exc:
            raise ProviderTimeout(str(exc)) from exc
        except (anthropic.RateLimitError, anthropic.APIConnectionError) as exc:
            raise ProviderTransient(str(exc)) from exc
        except anthropic.APIStatusError as exc:
            # 408 (request timeout) and 409 (conflict) are worth another attempt, as the SDK's own retries treat them.
            if exc.status_code >= 500 or exc.status_code in (408, 409):
                raise ProviderTransient(f"{exc.status_code}: {exc.message}") from exc
            raise ProviderError(f"{exc.status_code}: {exc.message}") from exc
        text = next((block.text for block in response.content if block.type == "text"), "")
        usage = response.usage
        result = ProviderResponse(
            text=text,
            model=response.model,
            input_tokens=usage.input_tokens or 0,
            output_tokens=usage.output_tokens or 0,
            cache_read_tokens=usage.cache_read_input_tokens or 0,
            cache_write_tokens=usage.cache_creation_input_tokens or 0,
            stop_reason=response.stop_reason or "",
        )
        if response.stop_reason == "refusal":
            category = getattr(response.stop_details, "category", None) if response.stop_details else None
            # A declined attempt is billed too; its tokens count toward the quota (D39).
            raise ProviderRefused(f"declined ({category or 'no category'})", response=result)
        return result


def recording_key(request: ProviderRequest) -> str:
    identity = json.dumps(
        [request.system, request.user, request.schema], ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(identity.encode()).hexdigest()


@dataclass
class RecordedProvider(ProviderBase):
    """Replays responses recorded from a real provider (CI and agent tests); a request without one fails."""

    directory: Path = Path(".")
    name: str = field(default="recorded", init=False)

    def complete(self, request: ProviderRequest) -> ProviderResponse:
        path = Path(self.directory) / f"{recording_key(request)}.json"
        if not path.exists():
            raise ProviderError(f"no recorded response for this request ({path.name})")
        recorded = json.loads(path.read_text(encoding="utf-8"))
        return ProviderResponse(**recorded["response"])


def record(provider: ProviderBase, request: ProviderRequest, directory: Path) -> ProviderResponse:
    """Calls a real provider and stores the response for RecordedProvider."""
    response = provider.complete(request)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{recording_key(request)}.json").write_text(
        json.dumps({"request": request.__dict__, "response": response.__dict__}, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8",
    )
    return response


def configured_provider() -> ProviderBase | None:
    """The provider named by settings, or None when AI is not configured (the product then runs on rules only)."""
    kind = settings.AI_PROVIDER
    if kind == "claude":
        if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
            return None
        return ClaudeProvider(model=settings.AI_MODEL, timeout=settings.AI_TIMEOUT_SECONDS)
    if kind == "recorded":
        return RecordedProvider(model=settings.AI_MODEL, directory=Path(settings.AI_RECORDINGS_DIR))
    return None
