"""Signals other apps follow without the programs app knowing them."""

from django.dispatch import Signal

#: A draft's rows changed (REST services or live-document materialization), sent inside the transaction.
#: Keyword argument: ``version``.
content_changed = Signal()
