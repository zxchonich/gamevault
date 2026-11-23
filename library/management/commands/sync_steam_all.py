"""Синхронізує всі Steam-акаунти, дані яких старші за STEAM_AUTOSYNC_HOURS.

    python manage.py sync_steam_all [--all] [--delay 2]

Для запуску за розкладом (Планувальник завдань Windows) — див. CLAUDE.md.
"""

import time

from django.core.management.base import BaseCommand

from library.models import ExternalAccount
from library.services.steam_autosync import stale_accounts, sync_account


class Command(BaseCommand):
    help = "Синхронізує застарілі Steam-бібліотеки (або всі з --all)."

    def add_arguments(self, parser):
        parser.add_argument("--all", action="store_true", help="Синхронізувати всі акаунти, а не лише застарілі.")
        parser.add_argument("--delay", type=float, default=2.0, help="Пауза між акаунтами, с (ліміти Steam).")

    def handle(self, *args, **options):
        accounts = ExternalAccount.objects.filter(provider="steam") if options["all"] else stale_accounts()
        accounts = list(accounts.select_related("user").order_by("last_synced_at"))
        if not accounts:
            self.stdout.write("Усі Steam-бібліотеки актуальні.")
            return

        ok = 0
        for index, account in enumerate(accounts):
            if index:
                time.sleep(options["delay"])
            result = sync_account(account)
            if result is None:
                self.stdout.write(self.style.WARNING(f"{account.user.username}: помилка Steam (див. лог)."))
            else:
                ok += 1
                self.stdout.write(
                    f"{account.user.username}: {result['synced_count']} ігор, додано {result['added_to_library_count']}."
                )
        self.stdout.write(self.style.SUCCESS(f"Готово: {ok} з {len(accounts)}."))
