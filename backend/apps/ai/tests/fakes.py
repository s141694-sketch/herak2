from dataclasses import dataclass, field

from apps.ai import providers
from apps.ai.gateway import ReleaseGate


@dataclass
class FakeProvider(providers.ProviderBase):
    """Plays a script of responses or exceptions, one per call, and keeps the requests it saw."""

    script: list = field(default_factory=list)
    requests: list = field(default_factory=list)
    name: str = field(default="fake", init=False)

    def complete(self, request):
        self.requests.append(request)
        outcome = self.script.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def answer(text, *, model="claude-opus-5-5", input_tokens=100, output_tokens=20, stop_reason="end_turn"):
    return providers.ProviderResponse(
        text=text, model=model, input_tokens=input_tokens, output_tokens=output_tokens, stop_reason=stop_reason
    )


class OpenGate(ReleaseGate):
    def is_released(self, spec, model):
        return True
