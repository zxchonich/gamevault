"""Вручну позначає email користувача підтвердженим (наприклад, для адміна з вигаданою адресою).

    python manage.py verify_email <логін> [<логін> ...]
"""

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from library.models import User


class Command(BaseCommand):
    help = "Позначає email користувачів підтвердженим."

    def add_arguments(self, parser):
        parser.add_argument("usernames", nargs="+")

    def handle(self, *args, usernames, **options):
        for username in usernames:
            user = User.objects.filter(username=username).first()
            if user is None:
                raise CommandError(f"Користувача {username} не знайдено.")
            if not user.email:
                raise CommandError(f"У {username} немає email — підтверджувати нічого.")
            if user.email_verified_at:
                self.stdout.write(f"{username}: email уже підтверджено.")
                continue
            user.email_verified_at = timezone.now()
            user.save(update_fields=["email_verified_at"])
            self.stdout.write(self.style.SUCCESS(f"{username}: email підтверджено."))
