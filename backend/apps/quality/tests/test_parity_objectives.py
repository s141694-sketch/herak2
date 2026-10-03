"""Verb extraction, Bloom levels and domains, and objective quality match Harak 1 on 1689 objectives."""

from apps.quality.rules.harak1 import bloom, objectives

from .parity import assert_matches, expected


def check(case):
    verb = bloom.extract_verb(case["input"])
    classified = bloom.classify_objective(case["input"])
    quality = objectives.check_objective(case["input"], classified)
    return [
        ("verb", verb, case["verb"]),
        ("lookupVerb", bloom.lookup_verb(verb) if verb else None, case["lookupVerb"]),
        ("lookupDomainVerb", bloom.lookup_domain_verb(verb) if verb else None, case["lookupDomainVerb"]),
        ("bloom", classified, case["bloom"]),
        ("objectiveBody", objectives.objective_body(case["input"]), case["objectiveBody"]),
        ("quality", quality, case["quality"]),
        (
            "dimensionOfBody",
            objectives.guess_dimension(objectives.objective_body(case["input"])),
            case["dimensionOfBody"],
        ),
    ]


def test_objectives_match_harak1():
    assert_matches(expected("objectives.json"), check)


def test_corpus_covers_every_outcome():
    cases = expected("objectives.json")
    seen = {(c["bloom"]["domain"], c["bloom"]["confidence"]) for c in cases}
    assert {
        ("cognitive", "high"),
        ("cognitive", "medium"),
        (None, "low"),
        ("affective", "high"),
        ("psychomotor", "medium"),
    } <= seen
    errors = {e for c in cases for e in c["quality"]["errors"]}
    assert errors == {"teacher-activity", "process", "topic", "multi", "unmeasurable"}
    assert any(c["lookupVerb"] and c["lookupVerb"].get("repaired") for c in cases)
