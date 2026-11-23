"""Middleware застосунку."""

from .access import SESSION_USER_KEY
from .services.steam_autosync import maybe_autosync


class SteamAutoSyncMiddleware:
    """Запускає фонову синхронізацію Steam, якщо дані користувача застаріли.

    Перевірка дешева (кеш), тому стоїть на кожному запиті; користувача з БД тут не беремо —
    достатньо id із сесії, а підробити його не можна (сесія підписана й зберігається на сервері)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        user_id = request.session.get(SESSION_USER_KEY) if hasattr(request, "session") else None
        if user_id and response.status_code < 400:
            maybe_autosync(user_id)
        return response
