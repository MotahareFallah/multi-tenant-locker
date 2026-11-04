from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from organizations.services import create_organization_with_admin


class Command(BaseCommand):
    help = "Create an organization with its own schema and its first admin."

    def add_arguments(self, parser):
        parser.add_argument("--name", required=True)
        parser.add_argument("--slug", required=True)
        parser.add_argument("--admin-phone", required=True)

    def handle(self, *args, name, slug, admin_phone, **options):
        try:
            organization = create_organization_with_admin(
                name=name, slug=slug, admin_phone=admin_phone
            )
        except ValidationError as exc:
            raise CommandError("; ".join(exc.messages)) from exc
        self.stdout.write(f"Created organization '{organization.slug}'.")
