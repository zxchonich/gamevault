import os
from unittest import mock

import requests
from django.test import RequestFactory, SimpleTestCase
from django.urls import reverse
from django.utils import timezone

from library.models import ExternalAccount, ExternalLibraryItem, Game, GameRequest, LibraryEntry
from library.services import steam_service
from library.services.steam_service import (
    SteamAppNotFound,
    SteamError,
    extract_steam_id_from_openid,
    get_owned_games,
    link_game_to_steam_owners,
    normalize_title,
    sync_steam_library,
    validate_steam_openid_response,
)

from .base import GameVaultTestCase


def fake_response(json_data=None, text="", status=200):
    response = mock.Mock(status_code=status, text=text)
    response.json.return_value = json_data
    response.raise_for_status.side_effect = (
        None if status < 400 else requests.HTTPError(f"{status}")
    )
    return response


def owned_game(appid, name, playtime=0, playtime_2weeks=0, last_played=0):
    return {
        "appid": appid,
        "name": name,
        "playtime_forever": playtime,
        "playtime_2weeks": playtime_2weeks,
        "rtime_last_played": last_played,
    }


class SteamServiceUnitTests(SimpleTestCase):
    def setUp(self):
        self.rf = RequestFactory()

    def test_extract_steam_id_accepts_only_steam_claimed_id(self):
        cases = {
            "https://steamcommunity.com/openid/id/76561197960287930": "76561197960287930",
            "https://evil.example/openid/id/76561197960287930": None,
            "https://steamcommunity.com/openid/id/123": None,
            "": None,
        }
        for claimed_id, expected in cases.items():
            with self.subTest(claimed_id=claimed_id):
                request = self.rf.get("/", {"openid.claimed_id": claimed_id})
                self.assertEqual(extract_steam_id_from_openid(request), expected)

    def openid_request(self, **overrides):
        identity = "https://steamcommunity.com/openid/id/76561197960287930"
        params = {
            "openid.mode": "id_res",
            "openid.op_endpoint": "https://steamcommunity.com/openid/login",
            "openid.claimed_id": identity,
            "openid.identity": identity,
            "openid.return_to": "http://testserver" + reverse("library:steam_callback"),
            "openid.response_nonce": "2026-11-23T10:00:00Zabc",
            "openid.signed": "signed,op_endpoint,claimed_id,identity,return_to,response_nonce,assoc_handle",
            "openid.sig": "sig",
        }
        params.update(overrides)
        return self.rf.get("/", params)

    def test_openid_rejects_foreign_or_unsigned_responses(self):
        valid = fake_response(text="ns:http://specs.openid.net/auth/2.0\nis_valid:true\n")
        with mock.patch("library.services.steam_service.requests.post", return_value=valid):
            cases = {
                "чужий return_to": {"openid.return_to": "https://evil.example/steam/callback/"},
                "чужий провайдер": {"openid.op_endpoint": "https://evil.example/openid/login"},
                "identity не збігається": {"openid.identity": "https://steamcommunity.com/openid/id/76561197960287931"},
                "return_to не підписаний": {"openid.signed": "signed,op_endpoint,claimed_id,identity,response_nonce"},
            }
            for name, override in cases.items():
                with self.subTest(name):
                    self.assertFalse(validate_steam_openid_response(self.openid_request(**override)))

    def test_validate_openid(self):
        valid = fake_response(text="ns:http://specs.openid.net/auth/2.0\nis_valid:true\n")
        with mock.patch.object(steam_service.requests, "post", return_value=valid):
            self.assertTrue(validate_steam_openid_response(self.openid_request()))
            self.assertFalse(validate_steam_openid_response(self.openid_request(**{"openid.mode": "cancel"})))

        with mock.patch.object(steam_service.requests, "post", side_effect=requests.Timeout):
            self.assertFalse(validate_steam_openid_response(self.openid_request()))

    @mock.patch.dict(os.environ, {"STEAM_API_KEY": ""})
    def test_owned_games_without_api_key(self):
        with self.assertRaisesMessage(SteamError, "STEAM_API_KEY"):
            get_owned_games("1")

    @mock.patch.dict(os.environ, {"STEAM_API_KEY": "key"})
    def test_owned_games_private_profile_and_network_error(self):
        with mock.patch.object(steam_service.requests, "get", return_value=fake_response({"response": {}})):
            with self.assertRaisesMessage(SteamError, "приватності"):
                get_owned_games("1")

        with mock.patch.object(steam_service.requests, "get", side_effect=requests.ConnectionError):
            with self.assertRaises(SteamError):
                get_owned_games("1")

        empty = fake_response({"response": {"game_count": 0}})
        with mock.patch.object(steam_service.requests, "get", return_value=empty):
            self.assertEqual(get_owned_games("1"), [])

    def test_normalize_title(self):
        self.assertEqual(normalize_title("The Witcher® 3: Wild Hunt™"), "the witcher 3 wild hunt")
        self.assertEqual(normalize_title("  STARDEW   valley "), "stardew valley")


class SteamSyncTests(GameVaultTestCase):
    def setUp(self):
        self.user = self.make_user("alice")
        self.account = self.make_steam_account(self.user)

    def sync(self, games, store=None):
        """store: {appid: дані Steam Store}; відсутні appid — "немає в Steam Store"."""
        store = store or {}

        def fake_fetch(appid, language):
            if str(appid) not in store:
                raise SteamAppNotFound("not found")
            return store[str(appid)]

        with mock.patch("library.services.steam_service.get_owned_games", return_value=games),                 mock.patch("library.services.steam_service._fetch_app_data", side_effect=fake_fetch):
            return sync_steam_library(self.user, self.account)

    def test_sync_imports_items_and_adds_catalog_games(self):
        played = self.make_game("Counter-Strike 2", steam_appid="730")
        unplayed = self.make_game("Hades", steam_appid="1145360")

        result = self.sync([
            owned_game(730, "Counter-Strike 2", playtime=600, playtime_2weeks=60, last_played=1700000000),
            owned_game(1145360, "Hades"),
            owned_game(578080, "PUBG"),
        ])

        self.assertEqual(result, {"synced_count": 3, "added_to_library_count": 2, "removed_count": 0,
                                  "catalog_added": 0, "catalog_linked": 0,
                                  "details_fetched": 3, "details_pending": 0})
        cs2 = ExternalLibraryItem.objects.get(user=self.user, external_game_id="730")
        self.assertEqual((cs2.playtime_minutes, cs2.playtime_2weeks_minutes), (600, 60))
        self.assertIsNotNone(cs2.last_played_at)
        self.assertEqual(LibraryEntry.objects.get(user=self.user, game=played).status, "playing")
        self.assertEqual(LibraryEntry.objects.get(user=self.user, game=unplayed).status, "planned")

    def test_sync_keeps_existing_status_and_removes_stale_items(self):
        game = self.make_game("Counter-Strike 2", steam_appid="730")
        self.make_entry(self.user, game, status="completed")
        self.make_steam_item(self.account, 999, "Refunded game", playtime=30)
        self.make_steam_item(self.account, 570, "Dota 2", playtime=89000)

        result = self.sync([owned_game(730, "Counter-Strike 2", playtime=100)])

        self.assertEqual(result["removed_count"], 1)
        self.assertEqual(LibraryEntry.objects.get(user=self.user, game=game).status, "completed")
        self.assertFalse(ExternalLibraryItem.objects.filter(external_game_id="999").exists())
        # Steam інколи не віддає гру з годинами (Dota 2) — її не стираємо.
        self.assertTrue(ExternalLibraryItem.objects.filter(external_game_id="570").exists())

    def test_link_game_to_steam_owners(self):
        bob = self.make_user("bob")
        bob_account = self.make_steam_account(bob, steam_id="76561197960287931")
        self.make_steam_item(self.account, 413150, "Stardew Valley", playtime=30, playtime_2weeks=30)
        self.make_steam_item(bob_account, 413150, "Stardew Valley")
        game = self.make_game("Stardew Valley", steam_appid="413150")

        self.assertEqual(link_game_to_steam_owners(game), 2)
        self.assertEqual(LibraryEntry.objects.get(user=self.user, game=game).status, "playing")
        self.assertEqual(LibraryEntry.objects.get(user=bob, game=game).status, "planned")
        self.assertEqual(link_game_to_steam_owners(game), 0)


class SteamAccountViewsTests(GameVaultTestCase):
    def setUp(self):
        self.user = self.make_user("alice")
        self.login(self.user)

    def callback(self, steam_id="76561197960287930"):
        with mock.patch("library.views.steam.validate_steam_openid_response", return_value=True), \
                mock.patch("library.views.steam.extract_steam_id_from_openid", return_value=steam_id), \
                mock.patch("library.views.steam.get_steam_profile", return_value=None), \
                mock.patch("library.views.steam.sync_steam_library",
                           return_value={"synced_count": 0, "added_to_library_count": 0,
                                         "removed_count": 0}) as sync_mock:
            response = self.client.get(reverse("library:steam_callback"))
        return response, sync_mock

    def test_callback_links_account_and_syncs(self):
        response, sync_mock = self.callback()

        self.assertRedirects(response, reverse("library:steam_library"))
        self.assertTrue(ExternalAccount.objects.filter(user=self.user, provider="steam").exists())
        sync_mock.assert_called_once()

    def test_callback_refuses_account_linked_to_another_user(self):
        self.make_steam_account(self.make_user("bob"))

        response, sync_mock = self.callback()

        self.assertRedirects(response, reverse("library:profile"), fetch_redirect_response=False)
        self.assertFalse(ExternalAccount.objects.filter(user=self.user).exists())
        sync_mock.assert_not_called()

    def test_sync_shows_steam_error(self):
        self.make_steam_account(self.user)
        with mock.patch("library.views.steam.sync_steam_library", side_effect=SteamError("Steam недоступний")):
            response = self.client.post(reverse("library:steam_sync_library"), follow=True)

        self.assertIn("Steam недоступний", self.messages_of(response))

    def test_disconnect_removes_imported_items_but_keeps_library(self):
        account = self.make_steam_account(self.user)
        self.make_steam_item(account, 730, "Counter-Strike 2")
        game = self.make_game("Counter-Strike 2", steam_appid="730")
        self.make_entry(self.user, game)

        self.client.post(reverse("library:steam_disconnect"))

        self.assertFalse(ExternalAccount.objects.filter(user=self.user).exists())
        self.assertFalse(ExternalLibraryItem.objects.filter(user=self.user).exists())
        self.assertTrue(LibraryEntry.objects.filter(user=self.user, game=game).exists())


class SteamLibraryViewsTests(GameVaultTestCase):
    def setUp(self):
        self.alice = self.make_user("alice")
        self.account = self.make_steam_account(self.alice)
        self.make_steam_item(self.account, 730, "Counter-Strike 2", playtime=600)
        self.make_steam_item(self.account, 578080, "PUBG", playtime=60)
        self.cs2 = self.make_game("Counter-Strike 2", steam_appid="730")

    def test_own_library_with_filters(self):
        self.login(self.alice)
        url = reverse("library:steam_library")

        cases = {"": 2, "?catalog=in": 1, "?catalog=out": 1, "?q=pubg": 1, "?sort=title": 2, "?sort=recent": 2}
        for query, expected in cases.items():
            with self.subTest(query=query):
                response = self.client.get(url + query)
                self.assertEqual(response.context["filtered_count"], expected)

        response = self.client.get(url)
        self.assertEqual(response.context["total_hours"], 11)
        self.assertEqual([i.external_game_id for i in response.context["items"]], ["730", "578080"])

    def test_privacy_of_other_users_steam_library(self):
        bob = self.make_user("bob")
        url = reverse("library:user_steam_library", args=[self.alice.id])
        self.login(bob)

        self.assertEqual(self.client.get(url).status_code, 200)

        self.alice.is_private = True
        self.alice.save(update_fields=["is_private"])
        self.assertRedirects(self.client.get(url), reverse("library:user_profile", args=[self.alice.id]),
                             fetch_redirect_response=False)

        self.make_friends(bob, self.alice)
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_steam_data_on_my_library_and_game_page(self):
        self.make_entry(self.alice, self.cs2)
        self.login(self.alice)

        self.assertContains(self.client.get(reverse("library:my_library")), "steam://nav/games/details/730")
        ExternalLibraryItem.objects.filter(external_game_id="730").update(playtime_2weeks_minutes=90)
        self.assertContains(self.client.get(reverse("library:my_library")), "steam://run/730")
        self.assertContains(self.client.get(reverse("library:game_detail", args=[self.cs2.id])), "steam://run/730")

    def test_profile_shows_steam_summary(self):
        self.login(self.alice)

        response = self.client.get(reverse("library:profile"))

        summary = response.context["steam_summary"]
        self.assertEqual((summary["games_count"], summary["total_hours"]), (2, 11))
        self.assertEqual(summary["top_games"][0].external_game_id, "730")


STORE_DETAILS = {
    "steam_appid": "578080",
    "title": "PUBG: BATTLEGROUNDS",
    "description": "Battle royale",
    "developer": "PUBG Corporation",
    "release_date": timezone.datetime(2017, 12, 21).date(),
    "header_image": "https://example.com/header.jpg",
}


class SteamAdminTests(GameVaultTestCase):
    def setUp(self):
        self.admin = self.make_user("root", admin=True)
        self.alice = self.make_user("alice")
        self.account = self.make_steam_account(self.alice)
        self.make_steam_item(self.account, 578080, "PUBG: BATTLEGROUNDS", playtime=120, playtime_2weeks=30)
        self.login(self.admin)

    @mock.patch("library.views.moderation.download_steam_poster", return_value=True)
    @mock.patch("library.views.moderation.fetch_store_details", return_value=STORE_DETAILS)
    def test_approve_steam_request_fills_data_and_links_owners(self, fetch_mock, poster_mock):
        request = GameRequest.objects.create(
            user=self.alice, title="PUBG: BATTLEGROUNDS", steam_appid="578080",
            status="pending", created_at=timezone.now(),
        )

        self.client.post(reverse("library:approve_request", args=[request.id]))

        game = Game.objects.get(steam_appid="578080")
        self.assertEqual((game.developer, game.description), ("PUBG Corporation", "Battle royale"))
        self.assertEqual(str(game.release_date), "2017-12-21")
        poster_mock.assert_called_once()
        self.assertEqual(LibraryEntry.objects.get(user=self.alice, game=game).status, "playing")
        request.refresh_from_db()
        self.assertEqual(request.status, "approved")

    def test_approve_request_for_existing_appid_does_not_duplicate(self):
        self.make_game("PUBG", steam_appid="578080")
        request = GameRequest.objects.create(
            user=self.alice, title="PUBG", steam_appid="578080", status="pending", created_at=timezone.now(),
        )

        self.client.post(reverse("library:approve_request", args=[request.id]))

        self.assertEqual(Game.objects.filter(steam_appid="578080").count(), 1)

    def test_matching_page_suggests_by_title(self):
        game = self.make_game("PUBG BATTLEGROUNDS")

        response = self.client.get(reverse("library:admin_steam_matching"))

        listed = {g.id: g for g in response.context["unlinked_games"]}
        self.assertEqual([c["external_game_id"] for c in listed[game.id].steam_candidates], ["578080"])

    def test_link_validation_and_success(self):
        game = self.make_game("PUBG")
        self.make_game("Counter-Strike 2", steam_appid="730")
        url = reverse("library:admin_steam_link", args=[game.id])

        for bad in ["abc", "730"]:
            with self.subTest(appid=bad):
                self.client.post(url, {"steam_appid": bad})
                game.refresh_from_db()
                self.assertIsNone(game.steam_appid)

        self.client.post(url, {"steam_appid": "578080"})
        game.refresh_from_db()
        self.assertEqual(game.steam_appid, "578080")
        self.assertTrue(LibraryEntry.objects.filter(user=self.alice, game=game).exists())

    @mock.patch("library.views.catalog_admin.fetch_store_details", return_value=STORE_DETAILS)
    def test_game_form_prefill_from_steam(self, fetch_mock):
        response = self.client.get(reverse("library:admin_game_add") + "?steam_appid=578080")

        form = response.context["form_data"]
        self.assertEqual((form["title"], form["developer"], form["release_date"]),
                         ("PUBG: BATTLEGROUNDS", "PUBG Corporation", "2017-12-21"))
        self.assertTrue(form["download_steam_poster"])

    def test_game_form_rejects_duplicate_appid(self):
        self.make_game("Counter-Strike 2", steam_appid="730")

        response = self.client.post(reverse("library:admin_game_add"), {"title": "CS2 copy", "steam_appid": "730"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["form_data"]["title"], "CS2 copy")
        self.assertEqual(Game.objects.filter(steam_appid="730").count(), 1)

    def test_game_form_with_new_appid_links_owners(self):
        response = self.client.post(reverse("library:admin_game_add"), {"title": "PUBG", "steam_appid": "578080"})

        game = Game.objects.get(steam_appid="578080")
        self.assertRedirects(response, reverse("library:game_detail", args=[game.id]))
        self.assertTrue(LibraryEntry.objects.filter(user=self.alice, game=game).exists())


class SteamAppsTests(GameVaultTestCase):
    """Обкладинки й жанри зі Steam Store (таблиця steam_apps)."""

    STORE = {
        "578080": {"name": "PUBG", "type": "game", "header_image": "https://img/578080.jpg",
                   "genres": [{"description": "Action"}, {"description": "Free To Play"}]},
        "3527290": {"name": "PEAK", "type": "game", "header_image": "https://img/peak.jpg",
                    "genres": [{"description": "Adventure"}, {"description": "Simulation"}]},
    }

    def fake_fetch(self, appid, language):
        if appid not in self.STORE:
            raise SteamAppNotFound("not found")
        return self.STORE[appid]

    def refresh(self, appids, **kwargs):
        from library.services.steam_service import refresh_steam_apps
        with mock.patch("library.services.steam_service._fetch_app_data", side_effect=self.fake_fetch) as fetch:
            return refresh_steam_apps(appids, **kwargs), fetch

    def test_refresh_stores_apps_and_marks_missing(self):
        from library.models import SteamApp

        stats, _ = self.refresh(["578080", "3527290", "1"])

        self.assertEqual((stats["fetched"], stats["not_found"], stats["pending"]), (2, 1, 0))
        pubg = SteamApp.objects.get(appid="578080")
        self.assertEqual((pubg.header_image, pubg.genre_list), ("https://img/578080.jpg", ["Action", "Free To Play"]))
        self.assertFalse(SteamApp.objects.get(appid="1").found)

    def test_refresh_skips_known_apps_and_respects_limit(self):
        self.refresh(["578080"])

        stats, fetch = self.refresh(["578080", "3527290", "1"], limit=1)

        # 578080 уже відомий, ліміт 1 з двох нових: першим іде "1" — його немає в Store, тож один запит
        # (для знайдених гри — ще один, українською, за описом).
        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(stats["pending"], 1)

        _, fetch = self.refresh(["578080"], refresh=True)
        self.assertEqual(fetch.call_count, 2)

    def test_refresh_stops_on_network_error(self):
        from library.models import SteamApp
        from library.services.steam_service import refresh_steam_apps

        with mock.patch("library.services.steam_service._fetch_app_data",
                        side_effect=SteamError("Steam недоступний")):
            stats = refresh_steam_apps(["578080", "3527290"])

        self.assertEqual((stats["fetched"], stats["pending"], stats["error"]), (0, 2, "Steam недоступний"))
        self.assertFalse(SteamApp.objects.exists())

    def test_cover_url_prefers_store_header(self):
        from library.services.steam_service import attach_steam_apps

        account = self.make_steam_account(self.make_user("alice"))
        peak = self.make_steam_item(account, 3527290, "PEAK")
        unknown = self.make_steam_item(account, 999, "Unknown")
        self.refresh(["3527290"])

        attach_steam_apps([peak, unknown])

        self.assertEqual(peak.cover_url, "https://img/peak.jpg")
        self.assertIn("/steam/apps/999/header.jpg", unknown.cover_url)

    def test_map_steam_genres_uses_catalog_and_aliases(self):
        from library.models import Genre
        from library.services.steam_service import catalog_genre_index, map_steam_genres

        action = Genre.objects.create(name="Action")
        simulator = Genre.objects.create(name="Simulator")

        mapped = map_steam_genres(["Action", "Simulation", "Free To Play", ""], catalog_genre_index())

        self.assertEqual(mapped, {action.id, simulator.id})

    def test_sync_reports_pending_details(self):
        user = self.make_user("alice")
        account = self.make_steam_account(user)
        self.login(user)
        games = [owned_game(i, f"Game {i}") for i in range(1, 26)]

        with mock.patch("library.services.steam_service.get_owned_games", return_value=games), \
                mock.patch("library.services.steam_service._fetch_app_data",
                           side_effect=SteamAppNotFound("not found")) as fetch:
            response = self.client.post(reverse("library:steam_sync_library"), follow=True)

        self.assertEqual(fetch.call_count, steam_service.STEAM_APPS_PER_SYNC)
        self.assertIn("ще 5 — під час наступних синхронізацій", self.messages_of(response)[0])
        self.assertEqual(ExternalLibraryItem.objects.filter(user=user).count(), 25)

    def test_fetch_steam_apps_command(self):
        from io import StringIO

        from django.core.management import call_command

        from library.models import SteamApp

        account = self.make_steam_account(self.make_user("alice"))
        self.make_steam_item(account, 578080, "PUBG")
        out = StringIO()

        with mock.patch("library.services.steam_service._fetch_app_data", side_effect=self.fake_fetch):
            call_command("fetch_steam_apps", "--delay", "0", stdout=out)

        self.assertTrue(SteamApp.objects.filter(appid="578080", found=True).exists())
        self.assertIn("Завантажено: 1", out.getvalue())

    def test_network_guard_blocks_unmocked_requests(self):
        from library.services.steam_service import refresh_steam_apps

        with self.assertRaisesMessage(AssertionError, "Справжній HTTP-запит"):
            refresh_steam_apps(["578080"])
