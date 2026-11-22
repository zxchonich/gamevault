from django.core.management.base import BaseCommand

from library.models import ExternalLibraryItem
from library.services.steam_service import refresh_steam_apps


class Command(BaseCommand):
    help = "Завантажує зі Steam Store обкладинки та жанри для ігор зі Steam-бібліотек користувачів."

    def add_arguments(self, parser):
        parser.add_argument("--refresh", action="store_true",
                            help="Оновити дані й для вже завантажених ігор.")
        parser.add_argument("--limit", type=int, default=None,
                            help="Максимум ігор за один запуск.")
        parser.add_argument("--delay", type=float, default=0.4,
                            help="Пауза між запитами, с (Steam обмежує частоту запитів).")

    def handle(self, *args, refresh=False, limit=None, delay=0.4, **options):
        appids = ExternalLibraryItem.objects.filter(provider="steam").values_list("external_game_id", flat=True)

        stats = refresh_steam_apps(appids, limit=limit, refresh=refresh, delay=delay)

        self.stdout.write(
            f"Завантажено: {stats['fetched']}, немає в Steam Store: {stats['not_found']}, "
            f"залишилось: {stats['pending']}"
        )
        if stats["error"]:
            self.stdout.write(self.style.WARNING(
                f"Зупинено: {stats['error']} Запустіть команду пізніше, щоб продовжити."
            ))
        else:
            self.stdout.write(self.style.SUCCESS("Готово."))
