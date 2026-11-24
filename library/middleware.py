"""Middleware застосунку."""

from .access import SESSION_USER_KEY
from .services.steam_autosync import maybe_autosync
from .services.steam_presence import maybe_poll
from .services.volts import maybe_daily_visit


class SteamAutoSyncMiddleware:
    """Запускає фонову синхронізацію Steam, якщо дані користувача застаріли, і опитування
    «хто зараз у грі» (steam_presence.maybe_poll), якщо з минулого минула хвилина, і нараховує
    волти за перший візит дня (volts.maybe_daily_visit).

    Перевірка дешева (кеш), тому стоїть на кожному запиті; користувача з БД тут не беремо —
    достатньо id із сесії, а підробити його не можна (сесія підписана й зберігається на сервері)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        user_id = request.session.get(SESSION_USER_KEY) if hasattr(request, "session") else None
        if user_id and response.status_code < 400:
            maybe_autosync(user_id)
            maybe_poll()
            maybe_daily_visit(user_id)
        return response
