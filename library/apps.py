import os
import sys

from django.apps import AppConfig


class LibraryConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'library'

    def ready(self):
        # Опитування Steam («хто зараз у грі») у фоні, поки працює runserver, — незалежно від відвідувань.
        # З автоперезавантаженням runserver запускає два процеси: працюємо лише в дочірньому (RUN_MAIN).
        from django.conf import settings

        if not settings.STEAM_PRESENCE or "runserver" not in sys.argv:
            return
        if os.environ.get("RUN_MAIN") != "true" and "--noreload" not in sys.argv:
            return
        from library.services.steam_presence import start_background_poller

        start_background_poller()
