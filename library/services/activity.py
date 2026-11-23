"""Стрічка активності: запис подій і їх читання для стрічки, головної та профілю.

Події записуються у view в момент дії (record_*). Видимість:
  * стрічка — власні події та події друзів;
  * чужі події видно, лише якщо користувач не вимкнув show_activity;
  * у чужому профілі — за тими ж правилами, що й профіль (can_view_profile перевіряє view).
"""

from dataclasses import dataclass, field
from datetime import timedelta

from django.db import models
from django.utils import timezone

from library.access import friend_ids
from library.models import ActivityEvent, ExternalLibraryItem, Game, Review
from library.services.steam_service import attach_steam_apps

# Повторні зміни статусу чи оцінки тієї самої гри протягом цього часу зливаються в одну подію.
MERGE_WINDOW = timedelta(minutes=10)

# Події, які групуються, якщо йдуть підряд від одного користувача в один день.
GROUPABLE_TYPES = {ActivityEvent.LIBRARY_ADD, ActivityEvent.STATUS_CHANGE}

FEED_PAGE_SIZE = 40

# Фільтри стрічки: ?filter=<ключ>. Значення — підпис для пігулки.
FEED_FILTERS = {
    "all": "Усі",
    "mine": "Мої",
    "friends": "Друзі",
    "reviews": "Оцінки",
    "completed": "Пройдене",
}


# --- Запис ---------------------------------------------------------------------

def _record_or_merge(user, event_type, game, **fields):
    """Створює подію або оновлює нещодавню таку саму (той самий тип і гра)."""
    now = timezone.now()
    recent = (
        ActivityEvent.objects
        .filter(user=user, event_type=event_type, game=game, created_at__gte=now - MERGE_WINDOW)
        .order_by("-created_at")
        .first()
    )
    if recent:
        for name, value in fields.items():
            setattr(recent, name, value)
        recent.created_at = now
        recent.save(update_fields=[*fields.keys(), "created_at"])
        return recent

    return ActivityEvent.objects.create(user=user, event_type=event_type, game=game, created_at=now, **fields)


def record_library_add(user, game):
    return ActivityEvent.objects.create(
        user=user, event_type=ActivityEvent.LIBRARY_ADD, game=game, created_at=timezone.now()
    )


def record_status_change(user, game, status):
    return _record_or_merge(user, ActivityEvent.STATUS_CHANGE, game, status=status)


def record_review(user, game, score):
    return _record_or_merge(user, ActivityEvent.REVIEW, game, score=score)


def record_steam_import(user, added_count):
    if added_count <= 0:
        return None
    return ActivityEvent.objects.create(
        user=user, event_type=ActivityEvent.STEAM_IMPORT, item_count=added_count, created_at=timezone.now()
    )


def record_friendship(user, other_user):
    return ActivityEvent.objects.create(
        user=user, event_type=ActivityEvent.FRIENDSHIP, target_user=other_user, created_at=timezone.now()
    )


def record_game_approved(requested_by, game):
    return ActivityEvent.objects.create(
        user=requested_by, event_type=ActivityEvent.GAME_APPROVED, game=game, created_at=timezone.now()
    )


def forget_game_activity(user, game, include_reviews=True):
    """Гру прибрано з бібліотеки — її події більше не показуємо."""
    types = [ActivityEvent.LIBRARY_ADD, ActivityEvent.STATUS_CHANGE]
    if include_reviews:
        types.append(ActivityEvent.REVIEW)
    ActivityEvent.objects.filter(user=user, game=game, event_type__in=types).delete()


def forget_review_activity(user, game):
    ActivityEvent.objects.filter(user=user, game=game, event_type=ActivityEvent.REVIEW).delete()


# --- Читання -------------------------------------------------------------------

@dataclass
class FeedItem:
    """Одна або кілька згрупованих подій для показу."""

    event_type: str
    user: object
    created_at: object
    games: list = field(default_factory=list)
    target_user: object = None
    status: str = None
    score: int = None
    item_count: int = None
    review_text: str = ""

    @property
    def game(self):
        return self.games[0] if self.games else None

    @property
    def extra_games_count(self):
        return max(0, len(self.games) - 3)


def _visible_to(viewer, queryset):
    """Прибирає чужі події користувачів, які вимкнули показ активності."""
    hidden_author = models.Q(user__show_activity=False) & ~models.Q(user=viewer)
    hidden_target = (
        models.Q(event_type=ActivityEvent.FRIENDSHIP, target_user__show_activity=False)
        & ~models.Q(target_user=viewer)
    )
    return queryset.exclude(hidden_author).exclude(hidden_target)


def _base_queryset():
    return ActivityEvent.objects.select_related("user", "game", "target_user").order_by("-created_at", "-id")


def group_events(events):
    items = []
    for event in events:
        last = items[-1] if items else None
        if (
            last is not None
            and event.event_type in GROUPABLE_TYPES
            and last.event_type == event.event_type
            and last.user.id == event.user_id
            and last.status == event.status
            and timezone.localdate(last.created_at) == timezone.localdate(event.created_at)
            and event.game is not None
        ):
            last.games.append(event.game)
            continue

        items.append(FeedItem(
            event_type=event.event_type,
            user=event.user,
            created_at=event.created_at,
            games=[event.game] if event.game else [],
            target_user=event.target_user,
            status=event.status,
            score=event.score,
            item_count=event.item_count,
        ))

    _attach_review_texts(items)
    return items


def _attach_review_texts(items):
    """Уривок тексту рецензії для подій-оцінок (один запит на всі події)."""
    reviews = [item for item in items if item.event_type == ActivityEvent.REVIEW and item.game]
    if not reviews:
        return

    texts = {
        (user_id, game_id): text
        for user_id, game_id, text in Review.objects.filter(
            user_id__in={item.user.id for item in reviews},
            game_id__in={item.game.id for item in reviews},
        ).values_list("user_id", "game_id", "text")
    }
    for item in reviews:
        item.review_text = texts.get((item.user.id, item.game.id)) or ""


def feed_events(viewer, kind="all"):
    """Queryset подій для стрічки: власні та друзів; kind — ключ із FEED_FILTERS."""
    friends = friend_ids(viewer)
    people = friends | {viewer.id}
    queryset = _base_queryset().filter(models.Q(user_id__in=people) | models.Q(target_user_id__in=people))

    if kind == "mine":
        queryset = queryset.filter(models.Q(user=viewer) | models.Q(target_user=viewer))
    elif kind == "friends":
        queryset = queryset.filter(user_id__in=friends)
    elif kind == "reviews":
        queryset = queryset.filter(event_type=ActivityEvent.REVIEW)
    elif kind == "completed":
        queryset = queryset.filter(event_type=ActivityEvent.STATUS_CHANGE, status="completed")

    return _visible_to(viewer, queryset)


def build_feed(viewer, limit=None, offset=0):
    queryset = feed_events(viewer)
    events = list(queryset[offset:offset + limit] if limit else queryset[offset:])
    return group_events(events)


def user_activity(viewer, owner, limit=10):
    """Остання активність owner для його профілю (доступ до профілю перевіряє view)."""
    if viewer.id != owner.id and not owner.show_activity:
        return []
    queryset = _base_queryset().filter(models.Q(user=owner) | models.Q(target_user=owner))
    return group_events(_visible_to(viewer, queryset)[:limit])


def now_playing(viewer, limit=8):
    """У що друзі (і сам користувач) грали в Steam останні 2 тижні."""
    people = friend_ids(viewer) | {viewer.id}
    items = (
        ExternalLibraryItem.objects
        .filter(user_id__in=people, provider="steam", playtime_2weeks_minutes__gt=0)
        .exclude(models.Q(user__show_activity=False) & ~models.Q(user=viewer))
        .select_related("user")
        .order_by("-playtime_2weeks_minutes")[:limit]
    )
    items = attach_steam_apps(items)
    games = {g.steam_appid: g for g in Game.objects.filter(steam_appid__in=[i.external_game_id for i in items])}
    for item in items:
        item.catalog_game = games.get(item.external_game_id)
    return items
