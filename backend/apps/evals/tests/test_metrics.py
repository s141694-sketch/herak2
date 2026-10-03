"""Agreement and accuracy measures against values computed by hand or published worked examples."""

import pytest

from apps.evals import metrics as m


def test_cohen_kappa_of_the_textbook_example():
    # 50 items: both yes 20, A yes B no 5, A no B yes 10, both no 15 -> po 0.7, pe 0.5, kappa 0.4.
    a = ["yes"] * 25 + ["no"] * 25
    b = ["yes"] * 20 + ["no"] * 5 + ["yes"] * 10 + ["no"] * 15
    assert m.cohen_kappa(a, b) == pytest.approx(0.4)


def test_fleiss_kappa_of_the_published_example():
    # Fleiss (1971) example as tabulated in common references: 10 subjects, 14 raters, 5 categories, kappa 0.210.
    table = [
        [0, 0, 0, 0, 14],
        [0, 2, 6, 4, 2],
        [0, 0, 3, 5, 6],
        [0, 3, 9, 2, 0],
        [2, 2, 8, 1, 1],
        [7, 7, 0, 0, 0],
        [3, 2, 6, 3, 0],
        [2, 5, 3, 2, 2],
        [6, 5, 2, 1, 0],
        [0, 2, 2, 3, 7],
    ]
    ratings = [[str(k) for k, count in enumerate(row) for _ in range(count)] for row in table]
    assert m.fleiss_kappa(ratings) == pytest.approx(0.20993, abs=1e-4)


def test_perfect_and_degenerate_agreement():
    assert m.cohen_kappa(["a", "a"], ["a", "a"]) == 1.0
    assert m.fleiss_kappa([["x", "x"], ["x", "x"]]) == 1.0
    assert m.percent_agreement([["a", "a", "b"], ["c", "c"]]) == pytest.approx((1 / 3 + 1) / 2)
    with pytest.raises(ValueError):
        m.fleiss_kappa([["a", "b"], ["a"]])


def test_accuracy_confusion_and_detection():
    gold = ["3", "3", "2", "5"]
    predicted = ["3", "2", "2", None]
    assert m.accuracy(gold, predicted) == 0.5
    assert m.confusion(gold, predicted) == {"3": {"3": 1, "2": 1}, "2": {"2": 1}, "5": {"none": 1}}
    scores = m.precision_recall(["wrong", "ok", "wrong", "ok"], ["wrong", "wrong", "ok", "ok"], "wrong")
    assert scores == {"precision": 0.5, "recall": 0.5, "f1": 0.5, "support": 2}
