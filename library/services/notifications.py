"""Особисті сповіщення: створення, прочитання, лічильник для шапки.

Сповіщення пишуться у view в момент дії (як і стрічка активності). Сповіщення про заявку
в друзі зникає, щойно заявку прийнято/відхилено/відкликано (FK connection з CASCADE прибирає
його й тоді, коли зв'язок видалено).
"""

from django.utils import timezone

from library.models import Notification

HEADER_LIMIT = 8


def _create(user, kind, **fields):
    return Notification.objects.create(user=user, kind=kind, created_at=timezone.now(), **fields)


def notify_friend_request(connection):
    return _create(connection.receiver, Notification.FRIEND_REQUEST, actor=connection.sender, connection=connection)


def notify_friend_accepted(connection):
    """Отримувач прийняв заявку: сповіщаємо відправника, а сповіщення-заявку прибираємо."""
    forget_friend_request(connection)
    return _create(connection.sender, Notification.FRIEND_ACCEPTED, actor=connection.receiver, connection=connection)


def forget_friend_request(connection):
    Notification.objects.filter(connection=connection, kind=Notification.FRIEND_REQUEST).delete()


def notify_game_request(game_request, approved, game=None):
    kind = Notification.GAME_APPROVED if approved else Notification.GAME_REJECTED
    return _create(game_request.user, kind, actor=game_request.moderator, game_request=game_request, game=game)


def unread(user):
    return Notification.objects.filter(user=user, read_at__isnull=True)


def unread_count(user):
    return unread(user).count()


def recent(user, limit=HEADER_LIMIT):
    return list(
        Notification.objects.filter(user=user)
        .select_related("actor", "game", "game_request")
        .order_by("-created_at", "-id")[:limit]
    )


def mark_read(user, kinds=None, game=None):
    """Позначає прочитаними непрочитані сповіщення користувача (усі, або певних типів / про гру)."""
    qs = unread(user)
    if kinds:
        qs = qs.filter(kind__in=kinds)
    if game is not None:
        qs = qs.filter(game=game)
    return qs.update(read_at=timezone.now())
