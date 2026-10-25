from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q
from django.utils import timezone

from accounts.models import OTPChallenge


class Command(BaseCommand):
    help = (
        "Delete OTP challenges older than --days that are closed or expired. "
        "Open challenges that can still be used are never deleted."
    )

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=30)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, days, dry_run, **options):
        retention = timedelta(days=days)
        # The per-phone hourly cap counts recent challenges, so deleting inside
        # that window would silently raise the cap.
        if days < 1 or retention.total_seconds() <= settings.OTP_RATE_WINDOW_SECONDS:
            raise CommandError(
                "--days must be at least 1 and longer than OTP_RATE_WINDOW_SECONDS."
            )
        now = timezone.now()
        stale = OTPChallenge.objects.filter(created_at__lt=now - retention).filter(
            Q(closed_at__isnull=False) | Q(expires_at__lt=now)
        )
        if dry_run:
            self.stdout.write(f"Would delete {stale.count()} challenge(s).")
            return
        deleted, _ = stale.delete()
        self.stdout.write(f"Deleted {deleted} challenge(s).")
