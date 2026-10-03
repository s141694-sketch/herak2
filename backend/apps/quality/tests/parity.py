"""Harak 1's recorded outputs (parity/expected, task 4.1) and a helper that reports every mismatch at once."""

import json
from functools import cache
from pathlib import Path

EXPECTED = Path(__file__).resolve().parents[4] / "parity" / "expected"


@cache
def expected(name: str):
    path = EXPECTED / name
    assert path.exists(), f"{path} is missing; it is produced by parity/extract.mjs and committed"
    return json.loads(path.read_text(encoding="utf-8"))


def assert_matches(cases, check, *, label=lambda case: case.get("input")):
    """Run ``check(case)`` -> list of (field, ours, harak1) differences over every case; fail listing the first few."""
    failures = []
    for case in cases:
        for field, ours, theirs in check(case):
            if ours != theirs:
                failures.append(f"{label(case)!r} {field}: ours={ours!r} harak1={theirs!r}")
    assert not failures, f"{len(failures)} differences from Harak 1, first ones:\n" + "\n".join(failures[:8])
