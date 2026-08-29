from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.accounts.models import User


class Command(BaseCommand):
    help = (
        "Ensures the admin account's email matches ADMIN_EMAIL from the "
        "environment. Creates the account with ADMIN_PASSWORD only if it "
        "doesn't exist yet; never overwrites an existing password."
    )

    def handle(self, *args, **options):
        admin_email = (settings.ADMIN_EMAIL or "").strip().lower()
        admin_password = settings.ADMIN_PASSWORD

        if not admin_email or not admin_password:
            raise CommandError(
                "ADMIN_EMAIL and ADMIN_PASSWORD must be set in your .env file."
            )

        admin = User.objects.filter(role=User.Role.ADMIN).order_by("created_at").first()

        if admin is None:
            User.objects.create_superuser(
                email=admin_email,
                phone_number=settings.ADMIN_PHONE_NUMBER,
                password=admin_password,
            )
            self.stdout.write(self.style.SUCCESS(f"Created admin account: {admin_email}"))
            return

        if admin.email != admin_email:
            admin.email = admin_email
            admin.save(update_fields=["email", "updated_at"])
            self.stdout.write(self.style.SUCCESS(f"Synced admin email to: {admin_email}"))
        else:
            self.stdout.write("Admin already exists — email unchanged, password left as-is.")