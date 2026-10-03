"""Agreement and accuracy measures for the golden set (spec 8.2). Pure functions over label lists."""

from collections import Counter
from itertools import combinations


def percent_agreement(ratings: list[list[str]]) -> float:
    """Share of agreeing rater pairs, averaged over items rated by two or more experts."""
    scores = []
    for labels in ratings:
        pairs = list(combinations(labels, 2))
        if pairs:
            scores.append(sum(a == b for a, b in pairs) / len(pairs))
    return sum(scores) / len(scores) if scores else 0.0


def cohen_kappa(a: list[str], b: list[str]) -> float:
    """Agreement of two raters on the same items beyond chance."""
    if len(a) != len(b) or not a:
        raise ValueError("two equally long, non-empty label lists are needed")
    n = len(a)
    observed = sum(x == y for x, y in zip(a, b, strict=True)) / n
    count_a, count_b = Counter(a), Counter(b)
    expected = sum(count_a[label] * count_b[label] for label in set(a) | set(b)) / (n * n)
    if expected == 1:
        return 1.0 if observed == 1 else 0.0
    return (observed - expected) / (1 - expected)


def fleiss_kappa(ratings: list[list[str]]) -> float:
    """Agreement of several raters, each item rated by the same number of raters (two or more)."""
    if not ratings:
        raise ValueError("no items")
    raters = len(ratings[0])
    if raters < 2 or any(len(labels) != raters for labels in ratings):
        raise ValueError("every item needs the same number of raters, at least two")
    n_items = len(ratings)
    categories = sorted({label for labels in ratings for label in labels})
    counts = [Counter(labels) for labels in ratings]
    p_items = [(sum(c[k] ** 2 for k in categories) - raters) / (raters * (raters - 1)) for c in counts]
    p_bar = sum(p_items) / n_items
    p_categories = [sum(c[k] for c in counts) / (n_items * raters) for k in categories]
    p_e = sum(p**2 for p in p_categories)
    if p_e == 1:
        return 1.0 if p_bar == 1 else 0.0
    return (p_bar - p_e) / (1 - p_e)


def accuracy(gold: list[str], predicted: list[str | None]) -> float:
    if not gold:
        return 0.0
    return sum(g == p for g, p in zip(gold, predicted, strict=True)) / len(gold)


def confusion(gold: list[str], predicted: list[str | None]) -> dict[str, dict[str, int]]:
    """gold label -> predicted label -> count; a missing prediction is counted as "none"."""
    table: dict[str, dict[str, int]] = {}
    for g, p in zip(gold, predicted, strict=True):
        row = table.setdefault(g, {})
        key = p if p is not None else "none"
        row[key] = row.get(key, 0) + 1
    return table


def precision_recall(gold: list[str], predicted: list[str | None], positive: str) -> dict[str, float]:
    """Detection of the positive class (for the alignment agent: a link that is wrong)."""
    tp = sum(g == positive and p == positive for g, p in zip(gold, predicted, strict=True))
    fp = sum(g != positive and p == positive for g, p in zip(gold, predicted, strict=True))
    fn = sum(g == positive and p != positive for g, p in zip(gold, predicted, strict=True))
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"precision": precision, "recall": recall, "f1": f1, "support": tp + fn}
