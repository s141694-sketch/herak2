"""The ported rule data and the JavaScript sources of the translated patterns are still Harak 1's."""

from apps.quality.rules.harak1 import data, objectives, structure

from .parity import expected


def test_rule_data_equals_harak1():
    theirs = expected("data.json")
    for key in (
        "bloomLevels",
        "pronounSuffixes",
        "verbSuffixes",
        "stopWords",
        "matchThresholds",
        "domainNames",
        "affective",
        "psychomotor",
        "dimensions",
    ):
        assert data.RAW[key] == theirs[key], key
    assert data.RAW["unmeasurableVerbs"] == theirs["qualityPatterns"]["unmeasurableVerbs"]
    for key, value in data.RAW["reader"].items():
        assert theirs["reader"][key] == value, key


def test_translated_patterns_come_from_harak1s_sources():
    theirs = expected("data.json")
    for name, source in objectives.JS_SOURCES.items():
        assert theirs["qualityPatterns"][name]["source"] == source, name
        assert theirs["qualityPatterns"][name]["flags"] == ""
    assert [
        (
            p["type"],
            p["heading"]["source"] if p["heading"] else None,
            p["item"]["source"] if p["item"] else None,
            p["numbered"],
        )
        for p in theirs["structurePatterns"]
    ] == [(p.type, p.heading_source, p.item_source, p.numbered) for p in structure.STRUCTURE_PATTERNS]
    assert theirs["objectiveLine"]["source"] == structure.OBJECTIVE_LINE_SOURCE
    assert theirs["objectiveLineLoose"]["source"] == structure.OBJECTIVE_LINE_LOOSE_SOURCE
    assert theirs["tashkeel"]["source"] == data.TASHKEEL_SOURCE
    assert theirs["reader"]["arabicChar"]["source"] == data.ARABIC_CHAR_SOURCE
