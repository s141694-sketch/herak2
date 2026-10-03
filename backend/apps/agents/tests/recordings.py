"""CI recordings of agent answers, in the format apps.ai.providers.record() writes.

No model credentials were available where these were made, so the answers are hand-written and marked
as such in each file; a recorded or hand-written answer is never evidence for the release gate (D41).
Rebuild them after a prompt change:

    uv run python manage.py shell --settings=config.settings.test \
        -c "from apps.agents.tests.recordings import build_all; build_all()"
"""

import json
from pathlib import Path

from apps.ai import gateway, providers

DIRECTORY = Path(__file__).with_name("recordings")
ORIGIN = "hand-written: no model credentials in the build session; replace with providers.record() output"


def write(spec, payload: dict, answer: dict, *, model: str = "claude-opus-5-5") -> Path:
    request = gateway._request(spec, payload)
    path = DIRECTORY / spec.name / f"{providers.recording_key(request)}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    response = providers.ProviderResponse(
        text=json.dumps(answer, ensure_ascii=False), model=model, input_tokens=600, output_tokens=80
    )
    path.write_text(
        json.dumps(
            {"origin": ORIGIN, "request": request.__dict__, "response": response.__dict__}, ensure_ascii=False, indent=1
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def build_all() -> None:
    from apps.agents.tests.examples import EXAMPLES

    for spec, payload, answer in EXAMPLES():
        write(spec, payload, answer)
