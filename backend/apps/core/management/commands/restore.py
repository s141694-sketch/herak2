"""Restores a backup folder into the configured database, which must be empty, and the configured file store,
then checks every table's rows and every file's bytes against the backup (spec 7.4, task 8.3, D83).

    DATABASE_URL=<a new, empty database> python manage.py restore <backup folder>
"""

from django.core.management.base import BaseCommand, CommandError

from apps.core import backup


class Command(BaseCommand):
    help = "Restore a backup into an empty database and the file store, and check it."

    def add_arguments(self, parser):
        parser.add_argument("source", help="a backup folder, as made by the backup command")

    def handle(self, *args, source, **options):
        try:
            report = backup.restore(source)
        except backup.RestoreError as exc:
            raise CommandError(str(exc)) from exc
        seconds = report["seconds"]
        self.stdout.write(
            f"restored {report['rows']} rows in {report['tables']} tables and {report['files']} files; "
            f"database {seconds['database']} s, files {seconds['files']} s; checked against the backup"
        )
