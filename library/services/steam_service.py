import datetime
import os
import re
import unicodedata
import urllib.parse

import requests
from django.core.files.base import ContentFile
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from library.models import ExternalLibraryItem, Game, Genre, LibraryEntry, SteamApp

STEAM_OPENID_URL = "https://steamcommunity.com/openid/login"
STEAM_PLAYER_SUMMARIES_URL = "https://api.steampowered.com/ISteamUser/GetPlayerSummaries/v0002/"
STEAM_OWNED_GAMES_URL = "https://api.steampowered.com/IPlayerService/GetOwnedGames/v0001/"
STEAM_APP_DETAILS_URL = "https://store.steampowered.com/api/appdetails"
STEAM_CDN_APP_URL = "https://cdn.cloudflare.steamstatic.com/steam/apps/{appid}/{file}"

STEAM_APPID_RE = re.compile(r"^\d{1,10}$")
MAX_POSTER_BYTES = 5 * 1024 * 1024

# Steam повертає claimed_id виду https://steamcommunity.com/openid/id/<SteamID64>
STEAM_CLAIMED_ID_RE = re.compile(r"^https?://steamcommunity\.com/openid/id/(\d{17})$")

REQUEST_TIMEOUT = 10

# Скільки нових ігор довантажувати зі Steam Store під час однієї синхронізації
# (кожна гра — окремий запит; решта довантажиться наступного разу або командою fetch_steam_apps).
STEAM_APPS_PER_SYNC = 20

# Жанри Steam, назви яких відрізняються від жанрів каталогу.
STEAM_GENRE_ALIASES = {
    "simulation": "simulator",
    "role playing": "rpg",
}


class SteamError(Exception):
    """Помилка роботи зі Steam. Текст повідомлення можна показувати користувачу."""


class SteamAppNotFound(SteamError):
    """Гри з таким appid немає в Steam Store (видалена, регіональна тощо)."""


def _get_api_key():
    api_key = os.getenv("STEAM_API_KEY")

    if not api_key:
        raise SteamError("Steam API ключ не налаштовано (змінна STEAM_API_KEY).")

    return api_key


def _steam_api_get(url, params):
    try:
        response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        return response.json()
    except (requests.RequestException, ValueError) as exc:
        raise SteamError("Не вдалося отримати дані зі Steam. Спробуйте пізніше.") from exc


def build_steam_login_url(request):
    callback_url = request.build_absolute_uri(reverse("library:steam_callback"))

    params = {
        "openid.ns": "http://specs.openid.net/auth/2.0",
        "openid.mode": "checkid_setup",
        "openid.return_to": callback_url,
        "openid.realm": request.build_absolute_uri("/"),
        "openid.identity": "http://specs.openid.net/auth/2.0/identifier_select",
        "openid.claimed_id": "http://specs.openid.net/auth/2.0/identifier_select",
    }

    return STEAM_OPENID_URL + "?" + urllib.parse.urlencode(params)


def extract_steam_id_from_openid(request):
    claimed_id = request.GET.get("openid.claimed_id", "")
    match = STEAM_CLAIMED_ID_RE.match(claimed_id)

    return match.group(1) if match else None


def validate_steam_openid_response(request):
    """Перевіряє підпис відповіді OpenID безпосередньо у Steam."""
    if request.GET.get("openid.mode") != "id_res":
        return False

    # Підпис Steam лише засвідчує, що відповідь видав Steam. Додатково перевіряємо, що вона
    # видана саме для нашого callback (інакше чужу підписану відповідь можна "переслати" нам)
    # і що підписані саме ті поля, яким ми довіряємо.
    callback_url = request.build_absolute_uri(reverse("library:steam_callback"))
    return_to = request.GET.get("openid.return_to", "")
    signed = set(request.GET.get("openid.signed", "").split(","))
    if (
        request.GET.get("openid.op_endpoint") != STEAM_OPENID_URL
        or return_to.split("?", 1)[0] != callback_url
        or request.GET.get("openid.claimed_id") != request.GET.get("openid.identity")
        or not {"op_endpoint", "claimed_id", "identity", "return_to", "response_nonce"} <= signed
    ):
        return False

    params = request.GET.copy()
    params["openid.mode"] = "check_authentication"

    try:
        response = requests.post(STEAM_OPENID_URL, data=params, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
    except requests.RequestException:
        return False

    return "is_valid:true" in response.text.splitlines()


def get_steam_profile(steam_id):
    """Публічний профіль Steam або None, якщо його не вдалося отримати."""
    try:
        data = _steam_api_get(STEAM_PLAYER_SUMMARIES_URL, {
            "key": _get_api_key(),
            "steamids": steam_id,
        })
    except SteamError:
        return None

    players = data.get("response", {}).get("players", [])

    if not players:
        return None

    player = players[0]

    return {
        "steam_id": player.get("steamid"),
        "username": player.get("personaname"),
        "profile_url": player.get("profileurl"),
        "avatar_url": player.get("avatarfull"),
    }


def get_owned_games(steam_id):
    data = _steam_api_get(STEAM_OWNED_GAMES_URL, {
        "key": _get_api_key(),
        "steamid": steam_id,
        "include_appinfo": 1,
        "include_played_free_games": 1,
        "format": "json",
    })

    payload = data.get("response", {})

    # Для приватного профілю Steam повертає порожній response без game_count.
    if "game_count" not in payload:
        raise SteamError(
            "Steam не віддав список ігор. Перевірте, що профіль і "
            "\"Деталі ігор\" відкриті в налаштуваннях приватності Steam."
        )

    return payload.get("games", [])


def sync_steam_library(user, steam_account):
    games = get_owned_games(steam_account.external_user_id)
    now = timezone.now()

    playtime_by_appid = {}

    with transaction.atomic():
        for game in games:
            appid = game.get("appid")
            name = game.get("name")

            if not appid or not name:
                continue

            appid = str(appid)
            playtime = game.get("playtime_forever") or 0
            playtime_by_appid[appid] = playtime
            last_played = game.get("rtime_last_played") or 0

            ExternalLibraryItem.objects.update_or_create(
                user=user,
                provider="steam",
                external_game_id=appid,
                defaults={
                    "external_account": steam_account,
                    "game_title": name,
                    "playtime_minutes": playtime,
                    "playtime_2weeks_minutes": game.get("playtime_2weeks") or 0,
                    "last_played_at": (
                        datetime.datetime.fromtimestamp(last_played, tz=datetime.timezone.utc)
                        if last_played else None
                    ),
                    "launch_url": f"steam://run/{appid}",
                    "synced_at": now,
                }
            )

        # Ігри, яких більше немає в акаунті Steam.
        removed_count, _ = (
            ExternalLibraryItem.objects
            .filter(user=user, provider="steam")
            .exclude(external_game_id__in=playtime_by_appid.keys())
            .delete()
        )

        # Додаємо до бібліотеки GameVault ігри з каталогу, що є в Steam.
        # Існуючі записи (і їхні статуси) не змінюються.
        added_to_library_count = 0
        catalog_games = Game.objects.filter(steam_appid__in=playtime_by_appid.keys())

        for catalog_game in catalog_games:
            if _add_to_library(user.id, catalog_game, playtime_by_appid[catalog_game.steam_appid], now):
                added_to_library_count += 1

    steam_account.last_synced_at = now
    steam_account.save(update_fields=["last_synced_at"])

    # Обкладинки та жанри нових ігор (мережеві запити — поза транзакцією).
    details = refresh_steam_apps(playtime_by_appid.keys(), limit=STEAM_APPS_PER_SYNC)

    return {
        "synced_count": len(playtime_by_appid),
        "added_to_library_count": added_to_library_count,
        "removed_count": removed_count,
        "details_fetched": details["fetched"] + details["not_found"],
        "details_pending": details["pending"],
    }


def is_valid_appid(value):
    return bool(value) and bool(STEAM_APPID_RE.match(value))


def steam_cover_url(appid):
    """Горизонтальна обкладинка за appid. Для частини нових ігор її немає за цим шляхом,
    тому в шаблонах потрібен запасний варіант (onerror)."""
    return STEAM_CDN_APP_URL.format(appid=appid, file="header.jpg")


def steam_store_url(appid):
    return f"https://store.steampowered.com/app/{appid}/"


def normalize_title(title):
    """Назва для порівняння: без регістру, ™/®/©, пунктуації та зайвих пробілів."""
    # Знаки ™®© прибираємо до NFKC, бо вона перетворює ™ на літери "TM".
    title = re.sub(r"[™®©]", "", title or "")
    title = unicodedata.normalize("NFKC", title).casefold()
    title = re.sub(r"[^\w]+", " ", title)
    return " ".join(title.split())


def _add_to_library(user_id, game, playtime_minutes, added_at):
    """Додає гру до бібліотеки GameVault, якщо її там ще немає. Повертає True, якщо додано."""
    _, created = LibraryEntry.objects.get_or_create(
        user_id=user_id,
        game=game,
        defaults={
            "status": "playing" if playtime_minutes > 0 else "planned",
            "added_at": added_at,
        }
    )
    return created


def link_game_to_steam_owners(game):
    """Після призначення грі steam_appid додає її до бібліотек усіх, у кого вона є в Steam."""
    if not game.steam_appid:
        return 0

    now = timezone.now()
    added = 0
    owners = (
        ExternalLibraryItem.objects
        .filter(provider="steam", external_game_id=game.steam_appid)
        .values_list("user_id", "playtime_minutes")
    )

    with transaction.atomic():
        for user_id, playtime in owners:
            if _add_to_library(user_id, game, playtime, now):
                added += 1

    return added


def _parse_store_date(value):
    for fmt in ("%d %b, %Y", "%b %d, %Y", "%d %B, %Y", "%B %d, %Y"):
        try:
            return datetime.datetime.strptime(value, fmt).date()
        except (TypeError, ValueError):
            continue
    return None


def _fetch_app_data(appid, language):
    try:
        response = requests.get(
            STEAM_APP_DETAILS_URL,
            params={"appids": appid, "l": language},
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        payload = (response.json() or {}).get(str(appid)) or {}
    except (requests.RequestException, ValueError, AttributeError) as exc:
        raise SteamError("Не вдалося отримати дані гри зі Steam Store. Спробуйте пізніше.") from exc

    if not payload.get("success"):
        raise SteamAppNotFound(f"Гру з appid {appid} не знайдено в Steam Store.")

    return payload.get("data") or {}


def fetch_store_details(appid):
    """Дані гри зі Steam Store: назва, опис, розробник, дата виходу, URL зображення."""
    data = _fetch_app_data(appid, "english")

    description = data.get("short_description") or ""
    try:
        # Український опис, якщо Steam його має (інакше Steam поверне англійський).
        description = _fetch_app_data(appid, "ukrainian").get("short_description") or description
    except SteamError:
        pass

    release = data.get("release_date") or {}

    return {
        "steam_appid": str(appid),
        "title": data.get("name") or "",
        "description": description,
        "developer": ", ".join(data.get("developers") or []),
        "release_date": None if release.get("coming_soon") else _parse_store_date(release.get("date")),
        "header_image": data.get("header_image") or "",
    }


def _download_image(url):
    try:
        response = requests.get(url, timeout=REQUEST_TIMEOUT, stream=True)
        if response.status_code != 200 or not response.headers.get("Content-Type", "").startswith("image/"):
            return None

        content = response.raw.read(MAX_POSTER_BYTES + 1, decode_content=True)
    except requests.RequestException:
        return None

    if not content or len(content) > MAX_POSTER_BYTES:
        return None

    return content


# Звідки дозволено завантажувати зображення (адреса header_image приходить з форми).
STEAM_IMAGE_HOST_SUFFIXES = (".steamstatic.com", ".steampowered.com", ".akamaihd.net")


def is_steam_image_url(url):
    parsed = urllib.parse.urlsplit(url)
    host = (parsed.hostname or "").lower()
    return parsed.scheme == "https" and any(host.endswith(suffix) for suffix in STEAM_IMAGE_HOST_SUFFIXES)


def download_steam_poster(game, header_image_url=""):
    """Завантажує постер гри зі Steam у game.poster (вертикальний, інакше header).
    Повертає True, якщо постер збережено. Сам game не зберігає."""
    appid = game.steam_appid

    candidates = [STEAM_CDN_APP_URL.format(appid=appid, file="library_600x900.jpg")]
    if header_image_url and is_steam_image_url(header_image_url):
        candidates.append(header_image_url)

    for url in candidates:
        content = _download_image(url)
        if content:
            game.poster.save(f"steam_{appid}.jpg", ContentFile(content), save=False)
            return True

    return False


def steam_items_by_appid(user, appids):
    """{appid: ExternalLibraryItem} для ігор користувача зі списку appid."""
    appids = [a for a in appids if a]
    if not user or not appids:
        return {}

    items = ExternalLibraryItem.objects.filter(
        user=user, provider="steam", external_game_id__in=appids
    )
    return {item.external_game_id: item for item in items}


def get_steam_summary(user, top_limit=5):
    """Зведення по Steam для профілю. None, якщо Steam не підключено."""
    from django.db.models import Max, Sum
    from library.models import ExternalAccount

    account = ExternalAccount.objects.filter(user=user, provider="steam").first()
    if account is None:
        return None

    items = ExternalLibraryItem.objects.filter(user=user, provider="steam")
    totals = items.aggregate(minutes=Sum("playtime_minutes"), last_synced=Max("synced_at"))

    return {
        "account": account,
        "games_count": items.count(),
        "total_hours": round((totals["minutes"] or 0) / 60),
        "last_synced_at": account.last_synced_at or totals["last_synced"],
        "top_games": attach_steam_apps(
            items.filter(playtime_minutes__gt=0).order_by("-playtime_minutes")[:top_limit]
        ),
        "recent_games": attach_steam_apps(
            items.filter(playtime_2weeks_minutes__gt=0).order_by("-playtime_2weeks_minutes")[:top_limit]
        ),
    }


def refresh_steam_apps(appids, limit=None, refresh=False, delay=0):
    """Завантажує зі Steam Store дані (назва, обкладинка, жанри) для appid, яких ще немає
    в steam_apps (або для всіх, якщо refresh=True). Зупиняється на першій мережевій помилці
    чи обмеженні частоти запитів Steam. Повертає лічильники."""
    import time

    appids = sorted({str(a) for a in appids if a})
    if not refresh:
        known = set(SteamApp.objects.filter(appid__in=appids).values_list("appid", flat=True))
        appids = [a for a in appids if a not in known]

    batch = appids if limit is None else appids[:limit]
    stats = {"fetched": 0, "not_found": 0, "pending": len(appids) - len(batch), "error": None}

    for index, appid in enumerate(batch):
        if delay and index:
            time.sleep(delay)

        try:
            data = _fetch_app_data(appid, "english")
        except SteamAppNotFound:
            SteamApp.objects.update_or_create(
                appid=appid, defaults={"found": False, "fetched_at": timezone.now()}
            )
            stats["not_found"] += 1
            continue
        except SteamError as exc:
            stats["error"] = str(exc)
            stats["pending"] += len(batch) - index
            break

        SteamApp.objects.update_or_create(
            appid=appid,
            defaults={
                "name": (data.get("name") or "")[:255] or None,
                "header_image": (data.get("header_image") or "")[:500] or None,
                "genres": ", ".join(g.get("description", "") for g in data.get("genres") or [])[:500],
                "found": True,
                "fetched_at": timezone.now(),
            },
        )
        stats["fetched"] += 1

    return stats


def attach_steam_apps(items):
    """Підвантажує SteamApp до ExternalLibraryItem (item.steam_app) — для точних обкладинок і жанрів."""
    items = list(items)
    appids = {item.external_game_id for item in items}
    apps = {app.appid: app for app in SteamApp.objects.filter(appid__in=appids, found=True)}

    for item in items:
        item.steam_app = apps.get(item.external_game_id)

    return items


def catalog_genre_index():
    """{нормалізована назва: id жанру каталогу} для зіставлення з жанрами Steam."""
    return {normalize_title(name): genre_id for genre_id, name in Genre.objects.values_list("id", "name")}


def map_steam_genres(steam_genres, genre_index):
    """Жанри Steam -> множина id жанрів каталогу (лише ті, що є в каталозі)."""
    result = set()
    for name in steam_genres:
        key = normalize_title(name)
        key = STEAM_GENRE_ALIASES.get(key, key)
        if key in genre_index:
            result.add(genre_index[key])
    return result

