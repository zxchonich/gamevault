"""Завантажує досягнення Steam для всіх ігор, у які грали (поступово це робить і опитування).

    python manage.py fetch_steam_achievements [--user <логін>] [--delay 1]
"""

import time

from django.core.management.base import BaseCommand, CommandError

from library.models import User
from library.services.steam_achievements import backfill_items, sync_user_game
from library.services.steam_service import SteamError


class Command(BaseCommand):
    help = "Завантажує досягнення Steam для ігор, у які грали."

    def add_arguments(self, parser):
        parser.add_argument("--user", help="Лише для цього користувача (логін).")
        parser.add_argument("--delay", type=float, default=1.0, help="Пауза між іграми, с (ліміти Steam).")

    def handle(self, *args, **options):
        user = None
        if options["user"]:
            user = User.objects.filter(username=options["user"]).first()
            if user is None:
                raise CommandError(f"Користувача {options['user']} не знайдено.")

        items = backfill_items(limit=100000, user=user)
        if not items:
            self.stdout.write("Досягнення всіх ігор уже завантажено.")
            return

        for index, item in enumerate(items, 1):
            if index > 1:
                time.sleep(options["delay"])
            try:
                new = sync_user_game(item.user_id, item.external_account.external_user_id, item.external_game_id)
            except SteamError as exc:
                self.stdout.write(self.style.WARNING(f"Steam: {exc} Зупинено на {index - 1} з {len(items)}."))
                return
            self.stdout.write(f"[{index}/{len(items)}] {item.game_title}: нових {new}")
        self.stdout.write(self.style.SUCCESS("Готово."))
