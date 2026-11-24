"""Перераховує досягнення GameVault для всіх користувачів.

    python manage.py award_site_achievements

Для користувачів, яким досягнення ще не рахували, видача тиха (без сповіщень і подій у стрічці) —
так значки за минулі дії не засипають стрічку. Решта отримує нові рівні як зазвичай.
"""

from django.core.management.base import BaseCommand

from library.models import User
from library.services.site_achievements import check


class Command(BaseCommand):
    help = "Перераховує досягнення GameVault для всіх користувачів."

    def handle(self, *args, **options):
        for user in User.objects.order_by("id"):
            silent = user.achievements_synced_at is None
            new = check(user)
            label = ", ".join(f"{a.title} {tier}" for a, tier in new) or "нічого нового"
            self.stdout.write(f"{user.username}{' (тихо)' if silent else ''}: {label}")
        self.stdout.write(self.style.SUCCESS("Готово."))
