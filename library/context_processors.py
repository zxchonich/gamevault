from django.conf import settings

from .access import get_current_user
from .services import notifications


def current_library_user(request):
    # get_current_user, а не просто id із сесії: він же перевіряє відбиток пароля,
    # тож шапка не покаже «увійшли» на пристрої, який розлогінила зміна пароля.
    user = get_current_user(request)
    context = {
        "current_library_user": user,
        "google_login_enabled": bool(settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET),
    }
    if user is not None:
        context["header_unread_count"] = notifications.unread_count(user)
        context["header_notifications"] = notifications.recent(user)
    return context
