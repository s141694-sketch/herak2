"""Backups and their restore (spec 7.4, task 8.3, D83): the database and the stored files, checked on the way
back so a restore that differs from its backup is never taken for a good one."""

import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta
from io import StringIO

import psycopg
import pytest
from django.core.management import CommandError, call_command
from django.db import connection
from django.test import override_settings

from apps.accounts.models import Organization
from apps.core import backup
from apps.files import storage
from apps.files.models import File
from apps.files.services import store
from apps.tenancy.context import organization_context

pytestmark = pytest.mark.django_db(transaction=True)


def conninfo(name: str | None = None) -> dict:
    settings = dict(connection.settings_dict)
    if name:
        settings["NAME"] = name
    return settings


def _psycopg(name: str) -> dict:
    s = connection.settings_dict
    return {
        "host": s["HOST"] or None,
        "port": s["PORT"] or None,
        "user": s["USER"],
        "password": s["PASSWORD"],
        "dbname": name,
    }


def _admin():
    return psycopg.connect(**_psycopg("postgres"), autocommit=True)


@pytest.fixture
def empty_database():
    name = f"{connection.settings_dict['NAME']}_restore"
    with _admin() as admin:
        admin.execute(f'DROP DATABASE IF EXISTS "{name}"')
        admin.execute(f'CREATE DATABASE "{name}"')
    yield name
    with _admin() as admin:
        admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


@pytest.fixture
def world():
    """Two stored files, in a bucket of this test's own (the store outlives each test)."""
    with override_settings(FILES_BUCKET=f"backup-{uuid.uuid4().hex[:12]}", FILES_CREATE_BUCKET=True):
        yield _world()


def _world():
    org = Organization.objects.create(name="مركز", slug="center")
    with organization_context(org):
        logo = store(
            b"\x89PNG\r\n\x1a\n" + b"0" * 64, name="شعار.png", content_type="image/png", kind=File.Kind.LOGO, actor=None
        )
        export = store(
            b"PK\x03\x04 word",
            name="برنامج - 1.docx",
            content_type="application/msword",
            kind=File.Kind.EXPORT,
            actor=None,
        )
    return {"org": org, "files": [logo, export]}


def test_a_backup_holds_the_database_its_counts_and_every_file(world, tmp_path):
    made = backup.backup(tmp_path)
    manifest = json.loads((made / "manifest.json").read_text())
    dump = made / "database.dump"
    assert manifest["database"]["sha256"] == hashlib.sha256(dump.read_bytes()).hexdigest()
    assert manifest["tables"]["accounts_organization"] == 1
    assert manifest["tables"]["files_file"] == 2
    kept = {f["key"]: f for f in manifest["files"]}
    for file in world["files"]:
        assert kept[file.key]["sha256"] == file.sha256
        assert hashlib.sha256((made / "files" / file.key).read_bytes()).hexdigest() == file.sha256


def test_a_backup_restores_into_an_empty_database_and_store(world, tmp_path, empty_database):
    made = backup.backup(tmp_path)
    with override_settings(FILES_BUCKET=f"restored-{uuid.uuid4().hex[:12]}", FILES_CREATE_BUCKET=True):
        report = backup.restore(made, database=conninfo(empty_database))
        for file in world["files"]:
            assert hashlib.sha256(storage.read(file.key)).hexdigest() == file.sha256
    assert report["files"] == 2
    assert report["rows"] == sum(json.loads((made / "manifest.json").read_text())["tables"].values())
    with psycopg.connect(**_psycopg(empty_database)) as restored:
        assert restored.execute("SELECT name FROM accounts_organization").fetchall() == [("مركز",)]


def test_restore_refuses_a_database_that_is_not_empty(world, tmp_path):
    made = backup.backup(tmp_path)
    with pytest.raises(backup.RestoreError) as refused:
        backup.restore(made, database=conninfo())
    assert refused.value.code == "database_not_empty"


def test_restore_refuses_a_backup_that_changed_and_touches_nothing(world, tmp_path, empty_database):
    made = backup.backup(tmp_path)
    (made / "files" / world["files"][1].key).write_bytes(b"PK\x03\x04 changed")
    with pytest.raises(backup.RestoreError) as refused:
        backup.restore(made, database=conninfo(empty_database))
    assert refused.value.code == "backup_changed"
    with psycopg.connect(**_psycopg(empty_database)) as restored:
        tables = restored.execute("SELECT count(*) FROM pg_tables WHERE schemaname = 'public'").fetchone()
    assert tables == (0,)


def test_backups_older_than_the_days_kept_are_removed(tmp_path):
    def made(days_ago):
        stamp = (datetime.now(UTC) - timedelta(days=days_ago)).strftime(backup.STAMP)
        folder = tmp_path / stamp
        folder.mkdir()
        (folder / "manifest.json").write_text("{}")
        return folder

    old, recent = made(15), made(13)
    other = tmp_path / "notes"
    other.mkdir()
    assert backup.prune(tmp_path, keep_days=14) == [old]
    assert not old.exists() and recent.exists() and other.exists()


def test_the_commands_back_up_and_refuse_a_restore_over_data(world, tmp_path):
    with override_settings(BACKUP_DIR=""), pytest.raises(CommandError):
        call_command("backup", stdout=StringIO())
    out = StringIO()
    call_command("backup", "--dest", str(tmp_path), stdout=out)
    [made] = [p for p in tmp_path.iterdir() if (p / "manifest.json").exists()]
    assert str(made) in out.getvalue()
    with pytest.raises(CommandError, match="database_not_empty"):
        call_command("restore", str(made))


# --- From the independent review of phase 8 ----------------------------------------------------------------------


@pytest.mark.parametrize("days", ["0", "-1"])
def test_fewer_than_one_day_kept_is_refused_before_anything_is_made(tmp_path, days):
    # 0 would have removed the backup just made and still said it was made.
    with pytest.raises(CommandError, match="at least one day"):
        call_command("backup", "--dest", str(tmp_path), "--keep-days", days, stdout=StringIO())
    with pytest.raises(ValueError):
        backup.backup(tmp_path, keep_days=0)
    assert not list(tmp_path.iterdir())


def test_a_failed_dump_says_why(world, tmp_path):
    tool = tmp_path / "pg_dump"
    tool.write_text("#!/bin/sh\necho 'pg_dump: error: aborting because of server version mismatch' >&2\nexit 1\n")
    tool.chmod(0o755)
    dest = tmp_path / "backups"
    with override_settings(BACKUP_PG_DUMP=str(tool)), pytest.raises(CommandError, match="server version mismatch"):
        call_command("backup", "--dest", str(dest), stdout=StringIO())
    assert not list(dest.iterdir())


def test_a_backup_cut_off_before_its_manifest_is_removed_once_a_day_old(tmp_path):
    def unfinished(hours_ago):
        folder = tmp_path / (datetime.now(UTC) - timedelta(hours=hours_ago)).strftime(backup.STAMP)
        folder.mkdir()
        (folder / "database.dump").write_bytes(b"part of a dump")  # killed before its manifest
        return folder

    stale, running = unfinished(30), unfinished(1)
    assert backup.prune(tmp_path, keep_days=14) == [stale]
    assert not stale.exists() and running.exists()
