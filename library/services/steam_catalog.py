"""Автоматичне поповнення каталогу іграми зі Steam-бібліотек користувачів.

Після синхронізації кожна гра акаунта, для якої вже завантажено дані Steam Store (SteamApp),
потрапляє в каталог без заявок і модерації:
  * гра каталогу без appid з такою самою назвою — прив'язується до Steam (без дубля);
  * інакше створюється нова гра з назвою, описом, розробником і датою зі Steam Store;
  * жанри — зі Steam: відсутні в каталозі жанри створюються, у наявних ігор жанри Steam
    додаються до вже проставлених (ручні не видаляються);
  * гра одразу додається в бібліотеки всіх, у кого вона є в Steam;
  * заявки на цю гру, що чекали модерації, схвалюються автоматично (автор отримує сповіщення).

Не потрапляють: не-ігри (DLC, демо, саундтреки, програми — app_type та «програмні» жанри
Steam), ігри з позначкою сексуального контенту 18+ (SteamApp.adult) і ігри, які адмін видалив
з каталогу (SteamApp.blocked).
"""

import logging

from django.db import DatabaseError, transaction
from django.db.models import Q
from django.utils import timezone

from library.models import ExternalLibraryItem, Game, GameGenre, GameRequest, Genre, SteamApp
from library.services.steam_service import STEAM_GENRE_ALIASES, STEAM_ITEM_FIELDS, _add_to_library, normalize_title

logger = logging.getLogger(__name__)


def _fit(value, model_field):
    """Обрізає текст до довжини поля Game (розробників у Steam буває кілька — ріжемо по комі)."""
    limit = Game._meta.get_field(model_field).max_length
    if not value or len(value) <= limit:
        return value
    cut = value[:limit]
    return cut.rsplit(",", 1)[0].strip() if "," in cut else cut.strip()


# Жанри Steam, якими позначено програми, а не ігри (Wallpaper Engine, редактори тощо).
SOFTWARE_GENRES = {
    "utilities", "animation modeling", "design illustration", "photo editing", "video production",
    "audio production", "software training", "web publishing", "game development", "education", "accounting",
}


def is_catalog_candidate(app):
    if not app.found or app.app_type != "game" or app.adult or app.blocked:
        return False
    return not {normalize_title(name) for name in app.genre_list} & SOFTWARE_GENRES


def _genre_resolver():
    """Функція «назва жанру Steam -> id жанру каталогу» (відсутні жанри створює)."""
    index = {normalize_title(name): genre_id for genre_id, name in Genre.objects.values_list("id", "name")}

    def resolve(steam_name):
        key = normalize_title(steam_name)
        key = STEAM_GENRE_ALIASES.get(key, key)
        if not key:
            return None
        if key not in index:
            index[key] = Genre.objects.create(name=steam_name.strip()[:50]).id
        return index[key]

    return resolve


def _add_steam_genres(games_with_apps):
    """Додає жанри Steam іграм каталогу (наявні жанри гри не чіпає)."""
    if not games_with_apps:
        return
    resolve = _genre_resolver()
    existing = set(
        GameGenre.objects.filter(game_id__in=[game.id for game, _ in games_with_apps]).values_list("game_id", "genre_id")
    )
    for game, app in games_with_apps:
        for name in app.genre_list:
            genre_id = resolve(name)
            if genre_id and (game.id, genre_id) not in existing:
                GameGenre.objects.create(game=game, genre_id=genre_id)
                existing.add((game.id, genre_id))


def _approve_waiting_requests(game, app):
    from library.services import notifications

    title_key = normalize_title(game.title)
    waiting = GameRequest.objects.filter(status="pending").filter(Q(steam_appid=app.appid) | Q(steam_appid__isnull=True) | Q(steam_appid=""))
    now = timezone.now()
    for game_request in waiting.select_related("user"):
        if game_request.steam_appid != app.appid and normalize_title(game_request.title) != title_key:
            continue
        game_request.status = "approved"
        game_request.reviewed_at = now
        game_request.save(update_fields=["status", "reviewed_at"])
        notifications.notify_game_request(game_request, approved=True, game=game)


def import_steam_games(appids):
    """Поповнює каталог іграми з appids. Повертає {"created", "linked", "added_to_libraries": {user_id: n}}."""
    appids = {str(a) for a in appids if a}
    result = {"created": 0, "linked": 0, "added_to_libraries": {}}
    if not appids:
        return result

    apps = {app.appid: app for app in SteamApp.objects.filter(appid__in=appids, found=True)}
    catalog = {game.steam_appid: game for game in Game.objects.filter(steam_appid__in=apps.keys())}
    unlinked = {}
    for game in Game.objects.filter(Q(steam_appid__isnull=True) | Q(steam_appid="")):
        unlinked.setdefault(normalize_title(game.title), game)
    item_titles = dict(
        ExternalLibraryItem.objects.filter(provider="steam", external_game_id__in=apps.keys())
        .values_list("external_game_id", "game_title")
    )

    genre_targets = [(catalog[appid], app) for appid, app in apps.items() if appid in catalog]
    now = timezone.now()

    for appid, app in sorted(apps.items()):
        if appid in catalog or not is_catalog_candidate(app):
            continue
        title = (app.name or item_titles.get(appid) or "").strip()[:150]
        if not title:
            continue

        try:
            with transaction.atomic():
                game = _import_one(appid, app, title, unlinked, now, result)
        except DatabaseError:
            # Одна проблемна гра не повинна зупиняти поповнення каталогу рештою.
            logger.exception("Не вдалося додати Steam-гру %s у каталог", appid)
            continue
        catalog[appid] = game
        genre_targets.append((game, app))

    _add_steam_genres(genre_targets)
    return result


def _import_one(appid, app, title, unlinked, now, result):
    """Прив'язує гру каталогу з такою ж назвою або створює нову; додає її власникам у бібліотеки."""
    game = unlinked.pop(normalize_title(title), None)
    if game is not None:
        game.steam_appid = appid
        game.description = game.description or app.description
        game.developer = game.developer or _fit(app.developer, "developer")
        game.release_date = game.release_date or app.release_date
        game.save()
        result["linked"] += 1
    else:
        game = Game.objects.create(
            title=title,
            description=app.description,
            developer=_fit(app.developer, "developer"),
            release_date=app.release_date,
            steam_appid=appid,
            created_at=now,
        )
        result["created"] += 1

    owners = ExternalLibraryItem.objects.filter(provider="steam", external_game_id=appid).values_list(
        "user_id", *STEAM_ITEM_FIELDS
    )
    for user_id, *item in owners:
        if _add_to_library(user_id, game, item, now):
            result["added_to_libraries"][user_id] = result["added_to_libraries"].get(user_id, 0) + 1

    _approve_waiting_requests(game, app)
    return game


def block_appid(appid):
    """Адмін видалив гру з каталогу — синхронізація не повинна повернути її знову."""
    if not appid:
        return
    SteamApp.objects.update_or_create(appid=appid, defaults={"blocked": True, "fetched_at": timezone.now()})
