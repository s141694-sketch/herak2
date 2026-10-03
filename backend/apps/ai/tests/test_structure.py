"""Structural guarantees of the gateway (spec 5.1, 7.5): only apps/ai/providers.py talks to an AI vendor, and
nothing outside apps.ai uses a provider directly, so every call passes the policy, quota, cache and validation."""

import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[3]
VENDOR = re.compile(r"^\s*(import anthropic|from anthropic\b|import openai|from openai\b)", re.MULTILINE)
PROVIDERS = re.compile(r"apps\.ai\.providers|from apps\.ai import providers|from \.providers|from \. import providers")


def sources():
    for path in sorted(BACKEND.rglob("*.py")):
        relative = path.relative_to(BACKEND).as_posix()
        if relative.startswith((".venv/", "apps/ai/tests/")) or "/migrations/" in relative:
            continue
        yield relative, path.read_text(encoding="utf-8")


def test_only_the_provider_module_imports_an_ai_vendor_sdk():
    offenders = [name for name, text in sources() if VENDOR.search(text) and name != "apps/ai/providers.py"]
    assert offenders == []


def test_only_the_gateway_uses_providers():
    allowed = {"apps/ai/gateway.py", "apps/ai/providers.py"}
    offenders = [name for name, text in sources() if PROVIDERS.search(text) and name not in allowed]
    assert offenders == []


def test_the_scan_sees_the_provider_module():
    assert any(name == "apps/ai/providers.py" for name, _ in sources())
