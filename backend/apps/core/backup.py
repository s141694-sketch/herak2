"""Backups of the database and the stored files, and their restore (spec 7.4, task 8.3, D83).

A backup is a folder named by its UTC time in the destination:

    database.dump   pg_dump's custom format, restored with pg_restore
    files/<key>     every object of the file store, under its key
    manifest.json   written last, so a folder without it is not a backup: the dump's and each file's SHA-256,
                    and the rows of every table, counted in the same snapshot the dump was taken from

A restore goes only into an empty database. It checks every checksum before it touches anything, and after it the
rows of every table and the bytes of every file, so a restore that differs from its backup fails loudly.
"""

import hashlib
import json
import os
import shutil
import subprocess
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psycopg
from botocore.exceptions import ClientError
from django.conf import settings
from django.db import connection
from psycopg import IsolationLevel, sql

from apps.files import storage

STAMP = "%Y%m%dT%H%M%SZ"
MANIFEST = "manifest.json"
CHUNK = 1024 * 1024


class BackupError(Exception):
    """A backup that could not be made, with the reason its tool gave."""


class RestoreError(Exception):
    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code


def _connection_args(database: dict) -> dict:
    return {
        "host": database.get("HOST") or None,
        "port": database.get("PORT") or None,
        "user": database.get("USER") or None,
        "password": database.get("PASSWORD") or None,
        "dbname": database["NAME"],
    }


def _tool_args(database: dict) -> tuple[list[str], dict]:
    """The PostgreSQL tools' connection options; the password goes in their environment, not on the command line."""
    args = []
    for option, key in (("--host", "HOST"), ("--port", "PORT"), ("--username", "USER")):
        if database.get(key):
            args += [option, str(database[key])]
    env = {**os.environ, "PGPASSWORD": database.get("PASSWORD") or ""}
    return [*args, "--dbname", database["NAME"]], env


def _tables(conn) -> list[str]:
    rows = conn.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename").fetchall()
    return [name for (name,) in rows]


def _counts(conn) -> dict[str, int]:
    count = sql.SQL("SELECT count(*) FROM {}")
    return {name: conn.execute(count.format(sql.Identifier(name))).fetchone()[0] for name in _tables(conn)}


def _inside(root: Path, key: str) -> Path:
    path = (root / key).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError(f"a file key leaves the backup: {key!r}")
    return path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def _copy_files(root: Path) -> list[dict]:
    if storage._local():  # the files are in a folder of this server (D98)
        copied = []
        for key in storage.keys():
            path = _inside(root, key)
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(storage._path(key), path)
            copied.append({"key": key, "size": path.stat().st_size, "sha256": _sha256(path)})
        return copied
    client = storage._server()
    copied = []
    try:
        pages = list(client.get_paginator("list_objects_v2").paginate(Bucket=settings.FILES_BUCKET))
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "NoSuchBucket":
            return copied  # nothing stored yet
        raise
    for page in pages:
        for item in page.get("Contents", []):
            path = _inside(root, item["Key"])
            path.parent.mkdir(parents=True, exist_ok=True)
            digest = hashlib.sha256()
            body = client.get_object(Bucket=settings.FILES_BUCKET, Key=item["Key"])["Body"]
            with path.open("wb") as out:
                for chunk in body.iter_chunks(CHUNK):
                    digest.update(chunk)
                    out.write(chunk)
            copied.append({"key": item["Key"], "size": path.stat().st_size, "sha256": digest.hexdigest()})
    return copied


def backup(dest, *, database: dict | None = None, keep_days: int | None = None) -> Path:
    """Backs up the database and the files into a new folder of ``dest``; returns the folder."""
    if keep_days is not None and keep_days < 1:
        # 0 would remove the backup just made (phase 8 review).
        raise ValueError("backups are kept at least one day")
    database = database or connection.settings_dict
    target = Path(dest) / datetime.now(UTC).strftime(STAMP)
    target.mkdir(parents=True)
    try:
        started = time.monotonic()
        with psycopg.connect(**_connection_args(database)) as conn:
            # One snapshot for the counts and the dump, so the manifest describes exactly what was dumped.
            conn.isolation_level = IsolationLevel.REPEATABLE_READ
            snapshot = conn.execute("SELECT pg_export_snapshot()").fetchone()[0]
            tables = _counts(conn)
            args, env = _tool_args(database)
            dump = target / "database.dump"
            done = subprocess.run(
                [settings.BACKUP_PG_DUMP, "--format=custom", "--no-owner", "--no-privileges", f"--snapshot={snapshot}"]
                + ["--file", str(dump), *args],
                env=env,
                capture_output=True,
                timeout=settings.BACKUP_SECONDS,
            )
            if done.returncode != 0:
                # Its own words: a version mismatch after a PostgreSQL upgrade (D83) says so here.
                reason = done.stderr.decode(errors="replace").strip()[-2000:]
                raise BackupError(f"pg_dump failed: {reason or f'exit status {done.returncode}'}")
        dumped = time.monotonic()
        files = _copy_files(target / "files")
        manifest = {
            "format": 1,
            "created_at": datetime.now(UTC).isoformat(),
            "database": {"file": dump.name, "size": dump.stat().st_size, "sha256": _sha256(dump)},
            "tables": tables,
            "files": files,
            "seconds": {"database": round(dumped - started, 2), "files": round(time.monotonic() - dumped, 2)},
        }
        partial = target / f"{MANIFEST}.partial"
        partial.write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
        partial.rename(target / MANIFEST)
    except BaseException:
        shutil.rmtree(target, ignore_errors=True)
        raise
    if keep_days is not None:
        prune(Path(dest), keep_days=keep_days, keep=target)
    return target


def prune(dest: Path, *, keep_days: int, keep: Path | None = None) -> list[Path]:
    """Removes the backups made more than ``keep_days`` ago, and backups cut off before their manifest (a killed
    container) once a day old; leaves anything that is not a backup alone, and ``keep``."""
    now = datetime.now(UTC)
    limit, unfinished_limit = now - timedelta(days=keep_days), now - timedelta(days=1)
    removed = []
    for folder in sorted(Path(dest).iterdir()):
        try:
            made = datetime.strptime(folder.name, STAMP).replace(tzinfo=UTC)
        except ValueError:
            continue
        if not folder.is_dir() or folder == keep:
            continue
        finished = (folder / MANIFEST).exists()
        if (finished and made < limit) or (not finished and made < unfinished_limit):
            shutil.rmtree(folder)
            removed.append(folder)
    return removed


def _check(source: Path, manifest: dict) -> None:
    dump = source / manifest["database"]["file"]
    if not dump.exists() or _sha256(dump) != manifest["database"]["sha256"]:
        raise RestoreError("backup_changed", "the database dump is missing or differs from its checksum")
    for file in manifest["files"]:
        path = _inside(source / "files", file["key"])
        if not path.exists() or _sha256(path) != file["sha256"]:
            raise RestoreError("backup_changed", f"file {file['key']!r} is missing or differs from its checksum")


def restore(source, *, database: dict | None = None) -> dict:
    """Restores a backup folder into an empty database and the configured file store, then checks both."""
    source = Path(source)
    manifest = json.loads((source / MANIFEST).read_text())
    _check(source, manifest)
    database = database or connection.settings_dict
    with psycopg.connect(**_connection_args(database)) as conn:
        if _tables(conn):
            raise RestoreError("database_not_empty", f"{database['NAME']} has tables: restore into a new database")
    started = time.monotonic()
    args, env = _tool_args(database)
    done = subprocess.run(
        [settings.BACKUP_PG_RESTORE, "--no-owner", "--no-privileges", "--exit-on-error", *args]
        + [str(source / manifest["database"]["file"])],
        env=env,
        capture_output=True,
        text=True,
        timeout=settings.BACKUP_SECONDS,
    )
    if done.returncode != 0:
        raise RestoreError("database_restore_failed", done.stderr[-2000:])
    restored = time.monotonic()
    with psycopg.connect(**_connection_args(database)) as conn:
        types = dict(conn.execute("SELECT key, content_type FROM files_file").fetchall())
        counts = _counts(conn)
    for file in manifest["files"]:
        data = _inside(source / "files", file["key"]).read_bytes()
        storage.write(file["key"], data, types.get(file["key"], "application/octet-stream"))
    differs = [name for name, rows in manifest["tables"].items() if counts.get(name) != rows]
    if differs:
        raise RestoreError("restore_differs", f"rows differ in {', '.join(differs)}")
    for file in manifest["files"]:
        if hashlib.sha256(storage.read(file["key"])).hexdigest() != file["sha256"]:
            raise RestoreError("restore_differs", f"file {file['key']!r} differs in the store")
    return {
        "tables": len(counts),
        "rows": sum(counts.values()),
        "files": len(manifest["files"]),
        "seconds": {"database": round(restored - started, 2), "files": round(time.monotonic() - restored, 2)},
    }
