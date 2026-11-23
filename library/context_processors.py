from django.conf import settings

from .access import get_current_user


def current_library_user(request):
    # get_current_user, а не просто id із сесії: він же перевіряє відбиток пароля,
    # тож шапка не покаже «увійшли» на пристрої, який розлогінила зміна пароля.
    return {
        "current_library_user": get_current_user(request),
        "google_login_enabled": bool(settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET),
    }
