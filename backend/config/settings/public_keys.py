"""Field encryption keys that are in git for development and tests (D64): they protect nothing, and production
refuses to start with either of them."""

DEVELOPMENT_FIELD_KEY = "ZGV2LW9ubHktZmllbGQtZW5jcnlwdGlvbi1rZXktMDE="
TEST_FIELD_KEY = "dGVzdC1vbmx5LWZpZWxkLWVuY3J5cHRpb24ta2V5LTE="
PUBLIC_FIELD_KEYS = frozenset({DEVELOPMENT_FIELD_KEY, TEST_FIELD_KEY})
