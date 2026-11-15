from django.contrib.auth.hashers import identify_hasher, make_password
from django.core.management.base import BaseCommand

from library.models import User


class Command(BaseCommand):
    help = "Хешує паролі користувачів, які ще зберігаються у відкритому вигляді."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Лише показати, яких користувачів це стосується.",
        )

    def handle(self, *args, dry_run=False, **options):
        updated = 0

        for user in User.objects.only("id", "username", "password_hash"):
            if not user.password_hash:
                self.stdout.write(self.style.WARNING(
                    f"  {user.username} (id={user.id}): порожній пароль, пропущено"
                ))
                continue

            try:
                identify_hasher(user.password_hash)
                continue
            except ValueError:
                pass

            updated += 1
            self.stdout.write(f"  {user.username} (id={user.id})")

            if not dry_run:
                user.password_hash = make_password(user.password_hash)
                user.save(update_fields=["password_hash"])

        verb = "Буде захешовано" if dry_run else "Захешовано"
        self.stdout.write(self.style.SUCCESS(f"{verb} паролів: {updated}"))
