import os
import re
import urllib.parse

import requests
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from library.models import Game, LibraryEntry, ExternalLibraryItem

STEAM_OPENID_URL = "https://steamcommunity.com/openid/login"
STEAM_PLAYER_SUMMARIES_URL = "https://api.steampowered.com/ISteamUser/GetPlayerSummaries/v0002/"
STEAM_OWNED_GAMES_URL = "https://api.steampowered.com/IPlayerService/GetOwnedGames/v0001/"

# Steam повертає claimed_id виду https://steamcommunity.com/openid/id/<SteamID64>
STEAM_CLAIMED_ID_RE = re.compile(r"^https?://steamcommunity\.com/openid/id/(\d{17})$")

REQUEST_TIMEOUT = 10


class SteamError(Exception):
    """Помилка роботи зі Steam. Текст повідомлення можна показувати користувачу."""


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

            ExternalLibraryItem.objects.update_or_create(
                user=user,
                provider="steam",
                external_game_id=appid,
                defaults={
                    "external_account": steam_account,
                    "game_title": name,
                    "playtime_minutes": playtime,
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
            status = "playing" if playtime_by_appid[catalog_game.steam_appid] > 0 else "planned"

            _, created = LibraryEntry.objects.get_or_create(
                user=user,
                game=catalog_game,
                defaults={
                    "status": status,
                    "added_at": now,
                }
            )

            if created:
                added_to_library_count += 1

    return {
        "synced_count": len(playtime_by_appid),
        "added_to_library_count": added_to_library_count,
        "removed_count": removed_count,
    }
