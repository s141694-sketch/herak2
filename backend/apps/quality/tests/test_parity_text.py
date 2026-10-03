"""Arabic normalization, token sets, word counts and the text reader's helpers match Harak 1 on 499 texts."""

from apps.quality.rules.harak1 import text

from .parity import assert_matches, expected


def test_text_functions_match_harak1():
    assert_matches(
        expected("text.json"),
        lambda case: [
            ("stripTashkeel", text.strip_tashkeel(case["input"]), case["stripTashkeel"]),
            ("unifyHamza", text.unify_hamza(case["input"]), case["unifyHamza"]),
            ("normalizeArabic", text.normalize_arabic(case["input"]), case["normalizeArabic"]),
            ("tokenSet", list(text.token_set(case["input"])), case["tokenSet"]),
            ("countWords", text.count_words(case["input"]), case["countWords"]),
            ("normalizeText", text.normalize_text(case["input"]), case["normalizeText"]),
            ("countArabicChars", text.count_arabic_chars(case["input"]), case["countArabicChars"]),
            ("reverseLines", text.reverse_lines(case["input"]), case["reverseLines"]),
            ("detectReversed", text.detect_reversed(case["input"]), case["detectReversed"]),
        ],
    )


def test_pagination_matches_harak1():
    assert_matches(
        expected("pagination.json"),
        lambda case: [
            ("pages", text.paginate_text(case["input"]), case["pages"]),
            ("pages100", text.paginate_text(case["input"], 100), case["pages100"]),
        ],
        label=lambda case: case["input"][:30],
    )


def test_jaccard_of_empty_sets_is_zero():
    assert text.jaccard(set(), {"x"}) == 0
