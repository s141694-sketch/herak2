"""Immutability of versioned content.

A *version* (framework version, template version, program version) is editable
only while its status is the editable one ("draft"). Rows that belong to a
version (competencies, levels, nodes, blocks, links) can be created, changed or
deleted only while that version is editable. Status changes of a locked
version happen only inside `lifecycle_write()`, which the single transition
point of each version type opens.

Enforced in three places: model save/delete, queryset update/delete, and (for
row tables) a PostgreSQL trigger created with `row_lock_trigger_sql`.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from django.db import models

from .errors import Conflict

_lifecycle_write: ContextVar[bool] = ContextVar("harak2_lifecycle_write", default=False)


class VersionLocked(Conflict):
    default_code = "version_locked"
    default_detail = "this version is locked and cannot be changed"


@contextmanager
def lifecycle_write() -> Iterator[None]:
    token = _lifecycle_write.set(True)
    try:
        yield
    finally:
        _lifecycle_write.reset(token)


class LockableVersionQuerySet(models.QuerySet):
    def _assert_all_editable(self) -> None:
        if _lifecycle_write.get():
            return
        if self.exclude(status=self.model.EDITABLE_STATUS).exists():
            raise VersionLocked()

    def update(self, **kwargs):
        self._assert_all_editable()
        return super().update(**kwargs)

    def delete(self):
        self._assert_all_editable()
        return super().delete()


class LockableVersion(models.Model):
    """A version whose stored status decides whether it and its rows may change."""

    EDITABLE_STATUS = "draft"

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        stored = self._stored_status()
        if stored is not None and stored != self.EDITABLE_STATUS and not _lifecycle_write.get():
            raise VersionLocked()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        stored = self._stored_status()
        if stored is not None and stored != self.EDITABLE_STATUS and not _lifecycle_write.get():
            raise VersionLocked()
        return super().delete(*args, **kwargs)

    @property
    def is_editable(self) -> bool:
        return self.status == self.EDITABLE_STATUS

    def _stored_status(self) -> str | None:
        if self.pk is None:
            return None
        return type(self)._base_manager.filter(pk=self.pk).values_list("status", flat=True).first()


class VersionedRowQuerySet(models.QuerySet):
    def _assert_all_editable(self) -> None:
        field = self.model.VERSION_FIELD
        editable = self.model.version_model().EDITABLE_STATUS
        if self.exclude(**{f"{field}__status": editable}).exists():
            raise VersionLocked()

    def update(self, **kwargs):
        self._assert_all_editable()
        return super().update(**kwargs)

    def delete(self):
        self._assert_all_editable()
        return super().delete()


class VersionedRow(models.Model):
    """A row that belongs to a LockableVersion through the field named VERSION_FIELD."""

    VERSION_FIELD = "version"

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        version_id = getattr(self, f"{self.VERSION_FIELD}_id")
        self._assert_version_editable(version_id)
        if self.pk is not None:
            stored_rows = type(self)._base_manager.filter(pk=self.pk)
            stored = stored_rows.values_list(f"{self.VERSION_FIELD}_id", flat=True).first()
            if stored is not None and stored != version_id:
                self._assert_version_editable(stored)
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        self._assert_version_editable(getattr(self, f"{self.VERSION_FIELD}_id"))
        return super().delete(*args, **kwargs)

    @classmethod
    def version_model(cls) -> type[LockableVersion]:
        return cls._meta.get_field(cls.VERSION_FIELD).related_model

    def _assert_version_editable(self, version_id) -> None:
        model = self.version_model()
        status = model._base_manager.filter(pk=version_id).values_list("status", flat=True).first()
        if status != model.EDITABLE_STATUS:
            raise VersionLocked()


def row_lock_trigger_sql(
    row_table: str, version_table: str, fk_column: str, editable: str = "draft"
) -> tuple[str, str]:
    """SQL that rejects INSERT, UPDATE and DELETE on rows of a non-editable version."""
    function = f"{row_table}_version_lock"
    forward = f"""
CREATE OR REPLACE FUNCTION {function}() RETURNS trigger AS $$
DECLARE
    st text;
BEGIN
    IF TG_OP IN ('UPDATE', 'DELETE') THEN
        SELECT status INTO st FROM {version_table} WHERE id = OLD.{fk_column};
        IF st IS NOT NULL AND st <> '{editable}' THEN
            RAISE EXCEPTION '{row_table}: version % is locked (%)', OLD.{fk_column}, st;
        END IF;
    END IF;
    IF TG_OP IN ('INSERT', 'UPDATE') THEN
        SELECT status INTO st FROM {version_table} WHERE id = NEW.{fk_column};
        IF st IS NOT NULL AND st <> '{editable}' THEN
            RAISE EXCEPTION '{row_table}: version % is locked (%)', NEW.{fk_column}, st;
        END IF;
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER {row_table}_version_lock
    BEFORE INSERT OR UPDATE OR DELETE ON {row_table}
    FOR EACH ROW EXECUTE FUNCTION {function}();
"""
    backward = f"""
DROP TRIGGER IF EXISTS {row_table}_version_lock ON {row_table};
DROP FUNCTION IF EXISTS {function}();
"""
    return forward, backward
