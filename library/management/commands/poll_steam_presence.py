"""Опитує Steam: хто зараз у грі (ігрові сесії, події в стрічці, досягнення).

    python manage.py poll_steam_presence            # одне опитування (для Планувальника завдань щохвилини)
    python manage.py poll_steam_presence --loop     # опитувати постійно, раз на STEAM_PRESENCE_INTERVAL

Поки працює runserver і сайтом користуються, опитування запускає й middleware; два процеси
не опитують одночасно (інтервал «застовплюється» в app_state).
"""

import time

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import close_old_connections

from library.services.steam_presence import claim_poll, poll


class Command(BaseCommand):
    help = "Опитує Steam: хто зараз у грі."

    def add_arguments(self, parser):
        parser.add_argument("--loop", action="store_true", help="Опитувати постійно (Ctrl+C — зупинити).")
        parser.add_argument("--force", action="store_true", help="Опитати, навіть якщо інтервал ще не минув.")

    def handle(self, *args, **options):
        if not options["loop"]:
            self._poll_once(force=options["force"])
            return

        self.stdout.write(f"Опитування Steam кожні {settings.STEAM_PRESENCE_INTERVAL} с. Ctrl+C — зупинити.")
        try:
            while True:
                self._poll_once(force=False)
                close_old_connections()
                time.sleep(max(5, settings.STEAM_PRESENCE_INTERVAL // 4))
        except KeyboardInterrupt:
            self.stdout.write("Зупинено.")

    def _poll_once(self, force):
        if not force and not claim_poll():
            return
        summary = poll()
        stamp = time.strftime("%H:%M:%S")
        if summary["error"]:
            self.stdout.write(self.style.WARNING(f"{stamp} помилка Steam: {summary['error']}"))
            return
        self.stdout.write(
            f"{stamp} акаунтів: {summary['accounts']}, у грі: {summary['playing']}, "
            f"почали: {summary['started']}, завершили: {summary['closed']}"
        )
