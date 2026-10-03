"""Importing a golden set the experts filled in (spec 8.2).

The CSV has one row per (item, expert): ``item_key``, ``expert``, ``label`` and the agent's input
columns. Every row of an item must carry the same input. The agreed label is the adjudicator's when
an expert named ``adjudicator`` labelled the item, otherwise the label most experts gave; a tie leaves
the item without an agreed label (it counts for expert agreement but not for agent accuracy).
"""

import csv
import hashlib
import io
import json
from collections import Counter

from django.db import transaction

from .evaluation import EvaluatedAgent
from .models import GoldenItem, GoldenSet

ADJUDICATOR = "adjudicator"


class GoldenSetError(ValueError):
    pass


def parse(agent: EvaluatedAgent, text: str) -> dict[str, dict]:
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    required = {"item_key", "expert", "label", *agent.input_fields}
    missing = required - set(reader.fieldnames or [])
    if missing:
        raise GoldenSetError(f"missing columns: {', '.join(sorted(missing))}")
    items: dict[str, dict] = {}
    for line, row in enumerate(reader, start=2):
        key, expert, label = row["item_key"].strip(), row["expert"].strip(), row["label"].strip()
        if not key or not expert:
            raise GoldenSetError(f"line {line}: item_key and expert are required")
        if label not in agent.labels:
            raise GoldenSetError(f"line {line}: label {label!r} is not one of {', '.join(agent.labels)}")
        values = {field: row[field].strip() for field in agent.input_fields}
        item = items.setdefault(key, {"input": values, "labels": {}})
        if item["input"] != values:
            raise GoldenSetError(f"line {line}: item {key} has a different input than on an earlier line")
        if expert in item["labels"]:
            raise GoldenSetError(f"line {line}: {expert} labelled item {key} twice")
        item["labels"][expert] = label
    if not items:
        raise GoldenSetError("the file has no rows")
    return items


def agreed_label(labels: dict[str, str]) -> str | None:
    if ADJUDICATOR in labels:
        return labels[ADJUDICATOR]
    ranked = Counter(labels.values()).most_common()
    if len(ranked) > 1 and ranked[0][1] == ranked[1][1]:
        return None
    return ranked[0][0]


@transaction.atomic
def import_set(agent: EvaluatedAgent, name: str, text: str, *, imported_by=None) -> GoldenSet:
    items = parse(agent, text)
    digest = hashlib.sha256(json.dumps(items, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    golden = GoldenSet.objects.create(agent=agent.name, name=name, content_hash=digest, imported_by=imported_by)
    GoldenItem.objects.bulk_create(
        GoldenItem(
            golden_set=golden,
            item_key=key,
            input=item["input"],
            labels=item["labels"],
            gold=agreed_label(item["labels"]),
        )
        for key, item in sorted(items.items())
    )
    return golden


def agreement(golden: GoldenSet) -> dict:
    """How far the experts agree: the realistic ceiling for an agent (spec 8.2)."""
    from . import metrics as m

    rows = [
        [label for expert, label in sorted(item.labels.items()) if expert != ADJUDICATOR] for item in golden.items.all()
    ]
    rated = [labels for labels in rows if len(labels) >= 2]
    result = {
        "items": len(rows),
        "items_with_two_or_more_experts": len(rated),
        "without_agreed_label": golden.items.filter(gold__isnull=True).count(),
        "percent_agreement": m.percent_agreement(rated),
    }
    sizes = {len(labels) for labels in rated}
    if len(sizes) == 1 and rated:
        result["fleiss_kappa"] = m.fleiss_kappa(rated)
    experts = sorted({e for item in golden.items.all() for e in item.labels if e != ADJUDICATOR})
    pairs = {}
    for i, a in enumerate(experts):
        for b in experts[i + 1 :]:
            both = [
                (item.labels[a], item.labels[b]) for item in golden.items.all() if a in item.labels and b in item.labels
            ]
            if both:
                pairs[f"{a}~{b}"] = m.cohen_kappa([x for x, _ in both], [y for _, y in both])
    result["cohen_kappa"] = pairs
    return result
