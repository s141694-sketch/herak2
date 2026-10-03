"""The text pipeline (reader, structure, Bloom, completeness, quality) matches Harak 1 on 12 curricula."""

import pytest

from apps.quality.rules.harak1 import bloom, objectives, structure, text

from .parity import expected

CASES = expected("documents.json")


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_document_matches_harak1(case):
    if "error" in case:
        with pytest.raises(text.ReaderError) as raised:
            text.read_text_document(f"{case['name']}.txt", case["input"])
        assert raised.value.code == case["error"]
        return
    doc = text.read_text_document(f"{case['name']}.txt", case["input"])
    assert doc == case["document"]
    struct = structure.structure(doc)
    assert struct == case["structure"]
    classified = bloom.classify_bloom(struct)
    assert classified == case["bloom"]
    completeness, stats = structure.summarize(struct, classified, doc)
    assert completeness == case["completeness"]
    assert stats == case["stats"]
    quality = objectives.check_objectives(struct, classified)
    assert quality == case["quality"]
    assert objectives.taxonomy_matrix(classified, quality) == case["taxonomyMatrix"]


def test_unsupported_type_is_refused():
    with pytest.raises(text.ReaderError) as raised:
        text.read_text_document("plan.xlsx", "x")
    assert raised.value.code == "UNSUPPORTED_TYPE"
