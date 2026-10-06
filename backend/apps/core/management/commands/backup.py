"""Backs up the database and the stored files into a new folder (spec 7.4, task 8.3, D83), then removes the
backups older than BACKUP_KEEP_DAYS.

    python manage.py backup [--dest DIR] [--keep-days N]
"""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.core import backup


class Command(BaseCommand):
    help = "Back up the database and the stored files."

    def add_arguments(self, parser):
        parser.add_argument("--dest", default=settings.BACKUP_DIR, help="the folder backups go in (BACKUP_DIR)")
        parser.add_argument("--keep-days", type=int, default=settings.BACKUP_KEEP_DAYS)

    def handle(self, *args, dest, keep_days, **options):
        if not dest:
            raise CommandError("no destination: pass --dest or set BACKUP_DIR")
        folder = backup.backup(dest, keep_days=keep_days)
        self.stdout.write(f"backed up to {folder}")
