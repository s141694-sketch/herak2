"""Lexical matching of objectives to competencies matches Harak 1's standards matching."""

from apps.quality.rules.harak1 import matching, text

from .parity import assert_matches, expected


def test_pairs_match_harak1():
    data = expected("matching.json")
    objectives, standards = data["objectives"], data["standards"]
    texts = [" ".join(part for part in (s["code"], s["text"]) if part) for s in standards]
    assert [list(text.token_set(t)) for t in texts] == data["standardTokens"]

    def check(pair):
        score = text.jaccard(text.token_set(objectives[pair["objective"]]), text.token_set(texts[pair["standard"]]))
        return [
            ("score", score, pair["score"]),
            ("rounded", matching.round_score(score), pair["rounded"]),
            ("confidence", matching.score_confidence(score), pair["confidence"]),
        ]

    assert_matches(expected("matching-pairs.json"), check, label=lambda p: (p["objective"], p["standard"]))


def test_ranked_matches_match_harak1():
    data = expected("matching.json")
    ours = matching.match_standards(data["objectives"], data["standards"])
    assert [
        {
            "objective": m["objective"],
            "standardId": m["standardId"],
            "standardText": m["standardText"],
            "score": m["score"],
            "confidence": m["confidence"],
        }
        for m in ours
    ] == data["matches"]


def test_rounding_and_threshold_edges_match_harak1():
    def check(case):
        score = text.jaccard(text.token_set(case["objective"]), text.token_set(case["competency"]))
        ranked = matching.match_standards([case["objective"]], [{"id": "X", "code": "", "text": case["competency"]}])
        return [
            ("score", score, case["score"]),
            ("rounded", matching.round_score(score), case["rounded"]),
            ("confidence", matching.score_confidence(score), case["confidence"]),
            ("matches", [{"score": m["score"], "confidence": m["confidence"]} for m in ranked], case["matches"]),
        ]

    assert_matches(expected("matching-edge.json"), check, label=lambda case: case["note"])
