from django.core.management.base import BaseCommand, CommandError

from accounts.maintenance import InvalidRetention, purge_otp_challenges


class Command(BaseCommand):
    help = (
        "Delete OTP challenges older than --days that are closed or expired. "
        "Open challenges that can still be used are never deleted."
    )

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=30)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, days, dry_run, **options):
        try:
            count = purge_otp_challenges(days=days, dry_run=dry_run)
        except InvalidRetention:
            raise CommandError(
                "--days must be at least 1 and longer than OTP_RATE_WINDOW_SECONDS."
            ) from None
        verb = "Would delete" if dry_run else "Deleted"
        self.stdout.write(f"{verb} {count} challenge(s).")
