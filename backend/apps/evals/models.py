"""Platform-level evaluation records (spec 5.5, 8.2): golden sets, the owner's thresholds and results.

These tables carry no organization: the golden set is built by the owner's experts for the product
as a whole, and an agent is released for every organization or for none.
"""

from django.conf import settings
from django.db import models


class GoldenSet(models.Model):
    agent = models.CharField(max_length=50)
    name = models.CharField(max_length=200)
    content_hash = models.CharField(max_length=64)
    imported_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["agent", "-created_at", "-id"]

    def __str__(self) -> str:
        return f"{self.agent}: {self.name}"


class GoldenItem(models.Model):
    golden_set = models.ForeignKey(GoldenSet, on_delete=models.CASCADE, related_name="items")
    item_key = models.CharField(max_length=100)
    input = models.JSONField()
    # expert -> label, as entered; the adjudicator's label (if any) is kept apart in ``gold``.
    labels = models.JSONField()
    gold = models.CharField(max_length=100, null=True, blank=True)  # noqa: DJ001 - null means "no agreed label"

    class Meta:
        ordering = ["golden_set", "item_key"]
        constraints = [models.UniqueConstraint(fields=["golden_set", "item_key"], name="evals_item_unique")]

    def __str__(self) -> str:
        return self.item_key


class AgentThreshold(models.Model):
    """The owner's minimum for one metric of one agent (spec 11, open question 4). No threshold, no release."""

    agent = models.CharField(max_length=50)
    metric = models.CharField(max_length=50)
    minimum = models.FloatField()
    note = models.TextField(blank=True)
    set_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["agent", "metric"]
        constraints = [models.UniqueConstraint(fields=["agent", "metric"], name="evals_threshold_unique")]

    def __str__(self) -> str:
        return f"{self.agent}.{self.metric} >= {self.minimum}"


class AgentEvaluation(models.Model):
    """One run of an agent version (prompt version + model) over a golden set."""

    agent = models.CharField(max_length=50)
    prompt_version = models.CharField(max_length=50)
    model = models.CharField(max_length=100)
    provider = models.CharField(max_length=30)
    golden_set = models.ForeignKey(GoldenSet, on_delete=models.PROTECT, related_name="evaluations")
    items = models.PositiveIntegerField()
    unanswered = models.PositiveIntegerField()
    metrics = models.JSONField()
    thresholds = models.JSONField()
    passed = models.BooleanField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self) -> str:
        return f"{self.agent} {self.prompt_version} on {self.model}: {'passed' if self.passed else 'failed'}"
