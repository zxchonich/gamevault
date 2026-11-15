import urllib.parse
import requests
import os
from library.models import Game, LibraryEntry, ExternalLibraryItem

STEAM_OPENID_URL = "https://steamcommunity.com/openid/login"
STEAM_PLAYER_SUMMARIES_URL = "https://api.steampowered.com/ISteamUser/GetPlayerSummaries/v0002/"


def build_steam_login_url(request):
    callback_url = request.build_absolute_uri("/steam/callback/")

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
    claimed_id = request.GET.get("openid.claimed_id")

    if not claimed_id:
        return None

    return claimed_id.rstrip("/").split("/")[-1]

def validate_steam_openid_response(request):
    params = request.GET.copy()
    params["openid.mode"] = "check_authentication"

    response = requests.post(
        STEAM_OPENID_URL,
        data=params,
        timeout=10
    )

    return "is_valid:true" in response.text

def get_steam_profile(steam_id):
    api_key = os.getenv("STEAM_API_KEY")

    if not api_key:
        return None

    params = {
        "key": api_key,
        "steamids": steam_id,
    }

    response = requests.get(
        STEAM_PLAYER_SUMMARIES_URL,
        params=params,
        timeout=10
    )

    if response.status_code != 200:
        return None

    data = response.json()
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

STEAM_OWNED_GAMES_URL = "https://api.steampowered.com/IPlayerService/GetOwnedGames/v0001/"


def get_owned_games(steam_id):
    api_key = os.getenv("STEAM_API_KEY")

    if not api_key:
        return []

    params = {
        "key": api_key,
        "steamid": steam_id,
        "include_appinfo": 1,
        "include_played_free_games": 1,
        "format": "json",
    }

    response = requests.get(
        STEAM_OWNED_GAMES_URL,
        params=params,
        timeout=10
    )

    if response.status_code != 200:
        return []

    data = response.json()

    return data.get("response", {}).get("games", [])

def sync_steam_library(user, steam_account):
    games = get_owned_games(steam_account.external_user_id)

    synced_count = 0
    added_to_library_count = 0

    for game in games:
        appid = str(game.get("appid"))
        name = game.get("name")

        if not appid or not name:
            continue

        ExternalLibraryItem.objects.update_or_create(
            user=user,
            provider="steam",
            external_game_id=appid,
            defaults={
                "external_account": steam_account,
                "game_title": name,
                "playtime_minutes": game.get("playtime_forever", 0),
                "launch_url": f"steam://run/{appid}",
            }
        )

        synced_count += 1

        catalog_game = Game.objects.filter(steam_appid=appid).first()

        if catalog_game:
            LibraryEntry.objects.update_or_create(
                user=user,
                game=catalog_game,
                defaults={
                    "status": "playing",
                }
            )

            added_to_library_count += 1

    return {
        "synced_count": synced_count,
        "added_to_library_count": added_to_library_count,
    }