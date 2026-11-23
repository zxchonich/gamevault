"""Автосинхронізація Steam у фоні.

maybe_autosync(user_id) викликається middleware на кожен запит увійшлого користувача, тому
вона дешева: перевірка «чи не пора» кешується на CHECK_INTERVAL, а сама синхронізація (кілька
секунд мережевих запитів) іде в окремому потоці, щоб сторінка не чекала. Блокування в кеші
не дає запустити дві синхронізації одного акаунта одночасно.

Для регулярної синхронізації без відвідувань — команда `python manage.py sync_steam_all`.
"""

import logging
import threading
from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.db import close_old_connections
from django.db.models import Q
from django.utils import timezone

from library.models import ExternalAccount

logger = logging.getLogger(__name__)

CHECK_INTERVAL = 10 * 60   # як часто для одного користувача взагалі перевіряти «чи не пора»
LOCK_TIMEOUT = 15 * 60     # страховка, якщо потік завис


def stale_before():
    return timezone.now() - timedelta(hours=settings.STEAM_AUTOSYNC_HOURS)


def stale_accounts():
    """Steam-акаунти, які давно не синхронізувались (або ще жодного разу)."""
    return ExternalAccount.objects.filter(provider="steam").filter(
        Q(last_synced_at__isnull=True) | Q(last_synced_at__lt=stale_before())
    )


def sync_account(account):
    """Синхронізує один акаунт. Повертає результат sync_steam_library або None при помилці Steam."""
    from library.services import activity
    from library.services.steam_service import SteamError, sync_steam_library

    try:
        result = sync_steam_library(account.user, account)
    except SteamError as exc:
        logger.warning("Автосинхронізація Steam для %s не вдалася: %s", account.user_id, exc)
        return None
    activity.record_steam_import(account.user, result["added_to_library_count"])  # подія лише якщо додано нове
    return result


def _lock_key(account_id):
    return f"steam-autosync:lock:{account_id}"


def _sync_and_unlock(account_id):
    try:
        account = ExternalAccount.objects.select_related("user").filter(id=account_id).first()
        if account is not None:
            sync_account(account)
    except Exception:  # фоновий потік не повинен падати мовчки
        logger.exception("Автосинхронізація Steam: неочікувана помилка (акаунт %s)", account_id)
    finally:
        cache.delete(_lock_key(account_id))


def _thread_main(account_id):
    try:
        _sync_and_unlock(account_id)
    finally:
        close_old_connections()  # у потоці своє з'єднання з БД — закриваємо його


def _start(account_id):
    """Окремий метод, щоб у тестах запускати синхронно (_sync_and_unlock)."""
    threading.Thread(target=_thread_main, args=(account_id,), name=f"steam-autosync-{account_id}", daemon=True).start()


def maybe_autosync(user_id):
    if not settings.STEAM_AUTOSYNC or not cache.add(f"steam-autosync:checked:{user_id}", 1, CHECK_INTERVAL):
        return False
    account = stale_accounts().filter(user_id=user_id).values_list("id", flat=True).first()
    if account is None or not cache.add(_lock_key(account), 1, LOCK_TIMEOUT):
        return False
    _start(account)
    return True
