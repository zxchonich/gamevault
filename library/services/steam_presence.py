"""Хто зараз у грі: опитування Steam і ігрові сесії.

Steam не надсилає подій сам, тому раз на STEAM_PRESENCE_INTERVAL секунд (за замовчуванням 60)
сайт питає GetPlayerSummaries для всіх прив'язаних Steam-акаунтів (до 100 за запит):
поле gameid/gameextrainfo є лише в того, хто зараз у грі (профіль і «Деталі ігор» мають бути
відкриті, у статусі «Невидимка» Steam гру не показує).

З відповідей будуються сесії (PlaySession):
  * гра з'явилася — відкривається сесія, друзям, у яких ця гра в бібліотеці, — сповіщення;
  * та сама гра — оновлюється last_seen_at;
  * гра зникла / змінилася / довго не було опитувань — сесія закривається (кінець — останнє
    опитування, де гру бачили), у стрічку пишеться «грає в …», потім перевіряються досягнення.

Хто запускає опитування:
  * фоновий потік, поки працює runserver (start_background_poller з LibraryConfig.ready) — основний спосіб;
  * middleware — запасний варіант, якщо сайт запущено не через runserver (поки сайтом користуються);
  * команда `python manage.py poll_steam_presence --loop` — окремим процесом, коли сервер не запущено.
Щоб два процеси не опитували одночасно, інтервал «застовплюється» атомарним UPDATE у app_state.
"""

import logging
import threading
from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.db import IntegrityError, close_old_connections
from django.utils import timezone

from library.access import friend_ids
from library.services import volts
from library.models import (
    AppState,
    ExternalAccount,
    ExternalLibraryItem,
    Game,
    LibraryEntry,
    Notification,
    PlaySession,
    SteamApp,
    User,
)
from library.services.steam_service import (
    STEAM_PLAYER_SUMMARIES_URL,
    SteamError,
    _get_api_key,
    _steam_api_get,
    is_valid_appid,
)

logger = logging.getLogger(__name__)

POLL_STATE = "steam_presence_poll"
BATCH_SIZE = 100                       # GetPlayerSummaries приймає до 100 steamid
STALE_AFTER = timedelta(minutes=5)     # без опитувань довше — статус «у грі» не показуємо
CONTINUE_GAP = timedelta(minutes=30)   # та сама гра після паузи в опитуваннях (перезапуск сервера) — та сама сесія
NOTIFY_COOLDOWN = timedelta(hours=12)  # не частіше одного сповіщення «друг грає в X» на гру
TICK_SECONDS = 15                      # як часто процес узагалі заглядає в БД (middleware)
LOCK_TIMEOUT = 5 * 60


def interval():
    return timedelta(seconds=settings.STEAM_PRESENCE_INTERVAL)


# --- Steam -----------------------------------------------------------------------------

def _fetch_summaries(steam_ids):
    data = _steam_api_get(STEAM_PLAYER_SUMMARIES_URL, {"key": _get_api_key(), "steamids": ",".join(steam_ids)})
    return data.get("response", {}).get("players", [])


def fetch_presence(steam_ids):
    """{steamid: (appid або None, назва)} для тих, хто зараз у грі."""
    result = {}
    for start in range(0, len(steam_ids), BATCH_SIZE):
        for player in _fetch_summaries(steam_ids[start:start + BATCH_SIZE]):
            game_id = str(player.get("gameid") or "")
            name = (player.get("gameextrainfo") or "").strip()
            if not game_id and not name:
                continue
            # Не-Steam ігри (ярлики) мають 64-бітний gameid — це не appid магазину.
            appid = game_id if is_valid_appid(game_id) and int(game_id) < 2**32 else None
            result[str(player.get("steamid"))] = (appid, name)
    return result


# --- Сесії -------------------------------------------------------------------------------

def _same_game(session, state):
    appid, name = state
    if appid or session.appid:
        return appid == session.appid
    return name == session.game_name


def _game_name(appid, name, game):
    if name:
        return name[:255]
    if game is not None:
        return game.title
    steam_name = SteamApp.objects.filter(appid=appid).values_list("name", flat=True).first() if appid else None
    return steam_name or f"Steam App {appid}"


def _is_first_play(user_id, appid):
    """Перший запуск: гра є в синхронізованій бібліотеці з 0 хвилин і сесій із нею ще не було."""
    if not appid or PlaySession.objects.filter(user_id=user_id, appid=appid).exists():
        return False
    return ExternalLibraryItem.objects.filter(
        user_id=user_id, provider="steam", external_game_id=appid, playtime_minutes=0
    ).exists()


def start_session(user_id, state, now):
    appid, name = state
    game = Game.objects.filter(steam_appid=appid).first() if appid else None
    session = PlaySession.objects.create(
        user_id=user_id,
        appid=appid,
        game=game,
        game_name=_game_name(appid, name, game),
        first_play=_is_first_play(user_id, appid),
        started_at=now,
        last_seen_at=now,
    )
    notify_friends(session)
    return session


def close_session(session):
    from library.services import activity

    session.ended_at = session.last_seen_at
    session.save(update_fields=["ended_at"])
    activity.record_play_session(session)
    volts.quietly(volts.session_reward, session)
    return session


def notify_friends(session):
    """Сповіщення друзям, у яких ця гра є в бібліотеці (з вимикачем у налаштуваннях)."""
    if session.game_id is None:
        return 0
    user = User.objects.filter(id=session.user_id).only("id", "show_playing_now").first()
    if user is None or not user.show_playing_now:
        return 0
    friends = friend_ids(user)
    if not friends:
        return 0
    targets = set(
        LibraryEntry.objects
        .filter(game_id=session.game_id, user_id__in=friends, user__notify_friend_playing=True)
        .values_list("user_id", flat=True)
    )
    targets -= set(
        Notification.objects.filter(
            kind=Notification.FRIEND_PLAYING,
            actor_id=user.id,
            game_id=session.game_id,
            user_id__in=targets,
            created_at__gte=session.started_at - NOTIFY_COOLDOWN,
        ).values_list("user_id", flat=True)
    )
    Notification.objects.bulk_create([
        Notification(
            user_id=target, kind=Notification.FRIEND_PLAYING, actor_id=user.id,
            game_id=session.game_id, created_at=session.started_at,
        )
        for target in targets
    ])
    return len(targets)


def poll(now=None):
    """Одне опитування Steam. Повертає підсумок (для команди й тестів)."""
    from library.services import steam_achievements

    now = now or timezone.now()
    accounts = list(ExternalAccount.objects.filter(provider="steam").values_list("user_id", "external_user_id"))
    summary = {"accounts": len(accounts), "playing": 0, "started": 0, "closed": 0, "error": None}

    presence = {}
    if accounts:
        try:
            presence = fetch_presence([steam_id for _, steam_id in accounts])
        except SteamError as exc:
            # Нічого не закриваємо: краще продовжити сесію наступним опитуванням, ніж обірвати.
            summary["error"] = str(exc)
            return summary

    open_sessions = {}
    for session in PlaySession.objects.filter(ended_at__isnull=True).order_by("started_at"):
        previous = open_sessions.get(session.user_id)
        if previous is not None:  # дубль (не мало б статися) — закриваємо старішу
            close_session(previous)
            summary["closed"] += 1
        open_sessions[session.user_id] = session

    still_playing = []
    for user_id, steam_id in accounts:
        state = presence.get(steam_id)
        current = open_sessions.pop(user_id, None)
        if current is not None:
            fresh = current.last_seen_at >= now - CONTINUE_GAP
            if state is not None and fresh and _same_game(current, state):
                still_playing.append(current.id)
                continue
            close_session(current)
            summary["closed"] += 1
        if state is not None:
            start_session(user_id, state, now)
            summary["started"] += 1

    PlaySession.objects.filter(id__in=still_playing).update(last_seen_at=now)
    summary["playing"] = len(still_playing) + summary["started"]

    for session in open_sessions.values():  # Steam відв'язано — сесію закриваємо
        close_session(session)
        summary["closed"] += 1

    try:
        summary["achievement_sessions"] = steam_achievements.process_pending_sessions()
        summary["achievement_backfill"] = steam_achievements.backfill()
    except SteamError as exc:
        logger.info("Досягнення Steam: %s", exc)
    return summary


# --- Хто запускає ------------------------------------------------------------------------

def claim_poll(now=None):
    """Атомарно «бере» поточний інтервал опитування (спільно для всіх процесів через БД)."""
    now = now or timezone.now()
    threshold = now - interval() + timedelta(seconds=5)
    if AppState.objects.filter(name=POLL_STATE, updated_at__lte=threshold).update(updated_at=now):
        return True
    if AppState.objects.filter(name=POLL_STATE).exists():
        return False
    try:
        AppState.objects.create(name=POLL_STATE, updated_at=now)
        return True
    except IntegrityError:
        return False


def _poll_and_unlock():
    try:
        poll()
    except Exception:  # фоновий потік не повинен падати мовчки
        logger.exception("Опитування Steam: неочікувана помилка")
    finally:
        cache.delete("steam-presence:lock")


def _thread_main():
    try:
        _poll_and_unlock()
    finally:
        close_old_connections()


def _start():
    """Окремий метод, щоб у тестах запускати синхронно (_poll_and_unlock)."""
    threading.Thread(target=_thread_main, name="steam-presence", daemon=True).start()


def _background_loop():
    import time

    while True:
        try:
            if claim_poll():
                poll()
        except Exception:  # потік має жити далі, навіть якщо одне опитування впало
            logger.exception("Фонове опитування Steam: неочікувана помилка")
        finally:
            close_old_connections()
        time.sleep(max(5, settings.STEAM_PRESENCE_INTERVAL // 4))


def start_background_poller():
    """Запускає фонове опитування в цьому процесі (один раз)."""
    if any(t.name == "steam-presence-loop" for t in threading.enumerate()):
        return False
    threading.Thread(target=_background_loop, name="steam-presence-loop", daemon=True).start()
    return True


def maybe_poll():
    """Викликається middleware: опитує Steam у фоні, якщо настав час."""
    if not settings.STEAM_PRESENCE or not cache.add("steam-presence:tick", 1, TICK_SECONDS):
        return False
    if not ExternalAccount.objects.filter(provider="steam").exists():
        return False
    if not cache.add("steam-presence:lock", 1, LOCK_TIMEOUT):
        return False
    if not claim_poll():
        cache.delete("steam-presence:lock")
        return False
    _start()
    return True


# --- Читання для сторінок -----------------------------------------------------------------

def _live_queryset(now=None):
    now = now or timezone.now()
    return PlaySession.objects.filter(ended_at__isnull=True, last_seen_at__gte=now - STALE_AFTER)


def _attach_steam_apps(sessions):
    apps = {a.appid: a for a in SteamApp.objects.filter(appid__in={s.appid for s in sessions if s.appid}, found=True)}
    for session in sessions:
        session.steam_app = apps.get(session.appid)
    return sessions


def live_sessions(viewer, limit=None):
    """Хто з друзів (і сам viewer) зараз у грі."""
    if viewer is None:
        return []
    people = friend_ids(viewer) | {viewer.id}
    queryset = (
        _live_queryset()
        .filter(user_id__in=people)
        .exclude(user__show_playing_now=False, user_id__in=people - {viewer.id})
        .select_related("user", "game")
        .order_by("started_at")
    )
    return _attach_steam_apps(list(queryset[:limit] if limit else queryset))


def live_for_users(viewer, users):
    """{user_id: сесія} для показу статусу біля конкретних користувачів (друзі й сам viewer)."""
    if viewer is None:
        return {}
    allowed = (friend_ids(viewer) | {viewer.id}) & {u.id for u in users}
    if not allowed:
        return {}
    sessions = (
        _live_queryset()
        .filter(user_id__in=allowed)
        .exclude(user__show_playing_now=False, user_id__in=allowed - {viewer.id})
        .select_related("game")
    )
    return {s.user_id: s for s in sessions}


def attach_live(viewer, users):
    """Ставить user.live_session (або None) — для карток друзів."""
    users = list(users)
    live = live_for_users(viewer, users)
    for user in users:
        user.live_session = live.get(user.id)
    return users


def live_in_game(viewer, game):
    """id друзів, які зараз грають у цю гру."""
    if viewer is None:
        return set()
    friends = friend_ids(viewer)
    return set(
        _live_queryset()
        .filter(user_id__in=friends, game=game, user__show_playing_now=True)
        .values_list("user_id", flat=True)
    )
