"""Досягнення Steam: завантаження, збереження і підготовка для сторінок.

Звідки беруться дані:
  * після кожної ігрової сесії (steam_presence) — досягнення цієї гри; отримані під час сесії
    потрапляють у стрічку подією «отримує N досягнень»;
  * поступове дозавантаження (backfill) — під час кожного опитування кілька ігор зі Steam-бібліотек,
    у які грали, але досягнення ще не перевіряли (без подій у стрічці, щоб не засипати старими);
  * команда `python manage.py fetch_steam_achievements` — усе одразу.

Назви, іконки й рідкість досягнень зберігаються один раз на appid (steam_achievements).
Мережеві виклики — _fetch_player_achievements і _fetch_schema (у тестах мокаються).
"""

import datetime
import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import timedelta

import requests
from django.db.models import F
from django.utils import timezone

from library.models import (
    ExternalAccount,
    ExternalLibraryItem,
    Game,
    PlaySession,
    SteamAchievement,
    SteamAchievementSchema,
    UserAchievement,
)
from library.services.steam_service import REQUEST_TIMEOUT, SteamError, _get_api_key

logger = logging.getLogger(__name__)

PLAYER_ACHIEVEMENTS_URL = "https://api.steampowered.com/ISteamUserStats/GetPlayerAchievements/v1/"
SCHEMA_URL = "https://api.steampowered.com/ISteamUserStats/GetSchemaForGame/v2/"
GLOBAL_PERCENT_URL = "https://api.steampowered.com/ISteamUserStats/GetGlobalAchievementPercentagesForApp/v2/"
LANGUAGE = "ukrainian"  # для ігор без перекладу Steam віддає англійські назви

SESSION_CHECKS_PER_POLL = 10   # скільки завершених сесій перевіряти за одне опитування
BACKFILL_PER_POLL = 3          # скільки ігор дозавантажувати за одне опитування
RECHECK_AFTER = timedelta(days=1)  # ігри, у які грали останні 2 тижні, перевіряються щонайбільше раз на добу
SESSION_MARGIN = timedelta(minutes=10)  # досягнення трохи до/після сесії теж зараховуються їй
RARE_PERCENT = 10              # «рідкісне» досягнення — у менш ніж 10% гравців


# --- Мережа ----------------------------------------------------------------------

def _get_json(url, params):
    """GET до Steam Web API. 4xx із JSON (гра без досягнень, закритий профіль) — не помилка."""
    try:
        response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
    except requests.RequestException as exc:
        raise SteamError("Не вдалося отримати дані зі Steam. Спробуйте пізніше.") from exc
    if response.status_code == 429 or response.status_code >= 500:
        raise SteamError("Steam тимчасово недоступний або обмежує кількість запитів.")
    try:
        return response.json()
    except ValueError:
        return {}


def _fetch_player_achievements(steam_id, appid):
    """[(apiname, unlocktime)] отриманих досягнень або None (у гри немає досягнень / закрито)."""
    data = _get_json(PLAYER_ACHIEVEMENTS_URL, {"key": _get_api_key(), "steamid": steam_id, "appid": appid})
    stats = data.get("playerstats") or {}
    if not stats.get("success"):
        return None
    return [
        (item["apiname"], int(item.get("unlocktime") or 0))
        for item in stats.get("achievements") or []
        if item.get("achieved") and item.get("apiname")
    ]


def _fetch_schema(appid):
    """Список досягнень гри (назва, опис, іконки, рідкість)."""
    data = _get_json(SCHEMA_URL, {"key": _get_api_key(), "appid": appid, "l": LANGUAGE})
    items = ((data.get("game") or {}).get("availableGameStats") or {}).get("achievements") or []
    if not items:
        return []

    percents = {}
    try:
        global_data = _get_json(GLOBAL_PERCENT_URL, {"gameid": appid})
        for row in (global_data.get("achievementpercentages") or {}).get("achievements") or []:
            percents[row.get("name")] = round(float(row.get("percent") or 0), 2)
    except (SteamError, TypeError, ValueError):
        pass  # рідкість — необов'язкова

    return [
        {
            "apiname": item["name"],
            "name": (item.get("displayName") or item["name"])[:255],
            "description": (item.get("description") or "")[:500] or None,
            "icon": item.get("icon") or None,
            "icon_gray": item.get("icongray") or None,
            "hidden": bool(item.get("hidden")),
            "percent": percents.get(item["name"]),
        }
        for item in items
        if item.get("name")
    ]


# --- Збереження -------------------------------------------------------------------

def _from_timestamp(value):
    return datetime.datetime.fromtimestamp(max(value, 0), tz=datetime.timezone.utc)


def ensure_schema(appid):
    """Завантажує досягнення гри (один раз на appid). Повертає їх кількість."""
    schema = SteamAchievementSchema.objects.filter(appid=appid).first()
    if schema is not None:
        return schema.total

    rows = _fetch_schema(appid)
    SteamAchievement.objects.bulk_create(
        [SteamAchievement(appid=appid, **row) for row in rows], ignore_conflicts=True
    )
    SteamAchievementSchema.objects.update_or_create(
        appid=appid, defaults={"total": len(rows), "fetched_at": timezone.now()}
    )
    return len(rows)


def sync_user_game(user_id, steam_id, appid):
    """Оновлює досягнення користувача в одній грі. Повертає кількість нових записів."""
    total = ensure_schema(appid)
    unlocked = _fetch_player_achievements(steam_id, appid) if total else None
    now = timezone.now()
    items = ExternalLibraryItem.objects.filter(user_id=user_id, provider="steam", external_game_id=appid)

    if unlocked is None:
        items.update(achievements_total=total, achievements_checked_at=now)
        return 0

    known = set(UserAchievement.objects.filter(user_id=user_id, appid=appid).values_list("apiname", flat=True))
    new = [
        UserAchievement(user_id=user_id, appid=appid, apiname=apiname, unlocked_at=_from_timestamp(unlocktime))
        for apiname, unlocktime in unlocked
        if apiname not in known
    ]
    UserAchievement.objects.bulk_create(new, ignore_conflicts=True)
    items.update(achievements_unlocked=len(unlocked), achievements_total=total, achievements_checked_at=now)
    return len(new)


def check_session(session, steam_id):
    """Після сесії: оновлює досягнення гри і записує в стрічку ті, що отримано під час сесії."""
    from library.services import activity

    if session.appid:
        sync_user_game(session.user_id, steam_id, session.appid)
        count = UserAchievement.objects.filter(
            user_id=session.user_id,
            appid=session.appid,
            unlocked_at__gte=session.started_at - SESSION_MARGIN,
            unlocked_at__lte=(session.ended_at or session.last_seen_at) + SESSION_MARGIN,
        ).count()
        if count:
            activity.record_achievements(session, count)
    PlaySession.objects.filter(id=session.id).update(achievements_checked=True)


def process_pending_sessions(limit=SESSION_CHECKS_PER_POLL):
    """Перевіряє досягнення завершених сесій. Повертає кількість перевірених."""
    sessions = list(
        PlaySession.objects
        .filter(ended_at__isnull=False, achievements_checked=False)
        .order_by("ended_at")[:limit]
    )
    if not sessions:
        return 0
    steam_ids = dict(
        ExternalAccount.objects.filter(provider="steam", user_id__in={s.user_id for s in sessions})
        .values_list("user_id", "external_user_id")
    )
    done = 0
    for session in sessions:
        steam_id = steam_ids.get(session.user_id)
        if steam_id is None or not session.appid:
            PlaySession.objects.filter(id=session.id).update(achievements_checked=True)
            continue
        check_session(session, steam_id)
        done += 1
    return done


def backfill_items(limit=BACKFILL_PER_POLL, user=None):
    """Ігри Steam-бібліотек, досягнення яких ще не перевіряли (або давно — для нещодавно зіграних)."""
    base = ExternalLibraryItem.objects.filter(provider="steam", playtime_minutes__gt=0)
    if user is not None:
        base = base.filter(user=user)
    never = base.filter(achievements_checked_at__isnull=True)
    stale = base.filter(playtime_2weeks_minutes__gt=0, achievements_checked_at__lt=timezone.now() - RECHECK_AFTER)
    order = (F("last_played_at").desc(nulls_last=True), "-playtime_minutes", "id")
    items = list(never.select_related("external_account").order_by(*order)[:limit])
    if len(items) < limit:
        items += list(stale.select_related("external_account").order_by(*order)[:limit - len(items)])
    return items


def backfill(limit=BACKFILL_PER_POLL, user=None):
    """Дозавантажує досягнення кількох ігор (без подій у стрічці). Повертає кількість ігор."""
    items = backfill_items(limit, user)
    for item in items:
        sync_user_game(item.user_id, item.external_account.external_user_id, item.external_game_id)
    return len(items)


# --- Читання для сторінок ----------------------------------------------------------

@dataclass
class AchievementView:
    appid: str
    apiname: str
    name: str
    description: str
    icon: str
    percent: object
    unlocked_at: object = None
    game_name: str = ""

    @property
    def is_rare(self):
        return self.percent is not None and self.percent < RARE_PERCENT


def _views(user_achievements, game_names=None):
    """UserAchievement -> AchievementView з назвами й іконками (один запит)."""
    if not user_achievements:
        return []
    appids = {ua.appid for ua in user_achievements}
    names = {ua.apiname for ua in user_achievements}
    schema = {
        (a.appid, a.apiname): a
        for a in SteamAchievement.objects.filter(appid__in=appids, apiname__in=names)
    }
    result = []
    for ua in user_achievements:
        info = schema.get((ua.appid, ua.apiname))
        result.append(AchievementView(
            appid=ua.appid,
            apiname=ua.apiname,
            name=info.name if info else ua.apiname,
            description=(info.description or "") if info else "",
            icon=(info.icon or "") if info else "",
            percent=info.percent if info else None,
            unlocked_at=ua.unlocked_at,
            game_name=(game_names or {}).get(ua.appid, ""),
        ))
    return result


def _game_names(user, appids):
    names = dict(
        ExternalLibraryItem.objects.filter(user=user, provider="steam", external_game_id__in=appids)
        .values_list("external_game_id", "game_title")
    )
    names.update(dict(Game.objects.filter(steam_appid__in=appids).values_list("steam_appid", "title")))
    return names


def recent_achievements(user, limit=8):
    """Останні отримані досягнення (для профілю)."""
    items = list(UserAchievement.objects.filter(user=user).order_by("-unlocked_at", "-id")[:limit])
    return _views(items, _game_names(user, {i.appid for i in items}))


def achievements_count(user):
    return UserAchievement.objects.filter(user=user).count()


def game_progress(user, appid, limit=8):
    """Прогрес користувача в грі для її сторінки або None, якщо даних немає."""
    if user is None or not appid:
        return None
    total = SteamAchievementSchema.objects.filter(appid=appid).values_list("total", flat=True).first()
    if not total:
        return None
    unlocked = list(UserAchievement.objects.filter(user=user, appid=appid).order_by("-unlocked_at", "-id"))
    if not unlocked:
        checked = ExternalLibraryItem.objects.filter(
            user=user, provider="steam", external_game_id=appid, achievements_unlocked__isnull=False
        ).exists()
        if not checked:
            return None
    views = _views(unlocked)
    rarest = min((v for v in views if v.percent is not None), key=lambda v: v.percent, default=None)
    return {
        "unlocked": len(unlocked),
        "total": total,
        "percent": round(len(unlocked) * 100 / total),
        "recent": views[:limit],
        "rarest": rarest,
    }


def attach_to_feed_items(items):
    """Іконки досягнень для подій «отримує N досягнень» (до 6 на подію, один-два запити)."""
    targets = [item for item in items if item.event_type == "achievements" and item.appid]
    if not targets:
        return
    since = min(timezone.localtime(item.created_at).replace(hour=0, minute=0, second=0, microsecond=0)
                for item in targets) - SESSION_MARGIN
    rows = list(
        UserAchievement.objects
        .filter(user_id__in={i.user.id for i in targets}, appid__in={i.appid for i in targets}, unlocked_at__gte=since)
        .order_by("-unlocked_at")
    )
    grouped = defaultdict(list)
    for view, row in zip(_views(rows), rows):
        grouped[(row.user_id, row.appid, timezone.localdate(row.unlocked_at))].append(view)
    for item in targets:
        item.achievements = grouped.get((item.user.id, item.appid, timezone.localdate(item.created_at)), [])[:6]
