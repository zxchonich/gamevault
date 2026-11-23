"""Автопоповнення каталогу зі Steam, «нещодавно зіграні» (Dota 2), кнопки запуску."""

from unittest import mock

from django.urls import reverse
from django.utils import timezone

from library.models import (
    ExternalLibraryItem, Game, GameGenre, GameRequest, Genre, LibraryEntry, Notification, SteamApp,
)
from library.services.steam_catalog import import_steam_games
from library.services.steam_service import get_owned_games, sync_steam_library

from .base import GameVaultTestCase


def steam_app(appid, name, genres="Action", app_type="game", **extra):
    return SteamApp.objects.create(
        appid=str(appid), name=name, app_type=app_type, genres=genres, found=True, fetched_at=timezone.now(),
        description=extra.pop("description", f"Опис {name}"), developer=extra.pop("developer", "Studio"), **extra,
    )


def game_genres(game):
    return set(GameGenre.objects.filter(game=game).values_list("genre__name", flat=True))


class OwnedGamesTests(GameVaultTestCase):
    def test_recently_played_games_are_merged(self):
        owned = {"response": {"game_count": 1, "games": [{"appid": 730, "name": "Counter-Strike 2"}]}}
        recent = {"response": {"games": [
            {"appid": 730, "name": "Counter-Strike 2"},
            {"appid": 570, "name": "Dota 2", "playtime_forever": 89119, "playtime_2weeks": 1146},
        ]}}
        with mock.patch("library.services.steam_service._steam_api_get", side_effect=[owned, recent]) as api, \
                mock.patch("library.services.steam_service._get_api_key", return_value="key"):
            games = get_owned_games("76561197960287930")
        self.assertEqual([g["appid"] for g in games], [730, 570])
        self.assertEqual(api.call_args_list[0].args[1]["skip_unvetted_apps"], 0)


class CatalogImportTests(GameVaultTestCase):
    def setUp(self):
        self.alice = self.make_user("alice")
        self.bob = self.make_user("bob")
        self.alice_steam = self.make_steam_account(self.alice)
        self.bob_steam = self.make_steam_account(self.bob, steam_id="76561197960287931")

    def own(self, account, appid, title, playtime=0):
        return self.make_steam_item(account, appid, title, playtime=playtime)

    def test_new_game_is_created_with_steam_data_genres_and_added_to_all_owners(self):
        Genre.objects.create(name="Simulator")
        steam_app(413150, "Stardew Valley", genres="Indie, Simulation, RPG", developer="ConcernedApe")
        self.own(self.alice_steam, 413150, "Stardew Valley", playtime=600)
        self.own(self.bob_steam, 413150, "Stardew Valley")

        result = import_steam_games(["413150"])

        game = Game.objects.get(steam_appid="413150")
        self.assertEqual((game.title, game.developer), ("Stardew Valley", "ConcernedApe"))
        self.assertEqual(game_genres(game), {"Indie", "Simulator", "RPG"})  # Simulation -> наявний Simulator
        self.assertEqual(LibraryEntry.objects.get(user=self.alice, game=game).status, "playing")
        self.assertEqual(LibraryEntry.objects.get(user=self.bob, game=game).status, "planned")
        self.assertEqual((result["created"], result["added_to_libraries"]), (1, {self.alice.id: 1, self.bob.id: 1}))

    def test_existing_unlinked_game_is_linked_by_title_and_keeps_manual_genres(self):
        moba = Genre.objects.create(name="MOBA")
        dota = self.make_game("Dota 2")
        GameGenre.objects.create(game=dota, genre=moba)
        steam_app(570, "Dota 2", genres="Action, Strategy, Free To Play")
        self.own(self.alice_steam, 570, "Dota 2", playtime=89119)

        result = import_steam_games(["570"])

        dota.refresh_from_db()
        self.assertEqual(dota.steam_appid, "570")
        self.assertEqual(Game.objects.filter(title="Dota 2").count(), 1)
        self.assertEqual(game_genres(dota), {"MOBA", "Action", "Strategy", "Free To Play"})
        self.assertTrue(LibraryEntry.objects.filter(user=self.alice, game=dota).exists())
        self.assertEqual((result["created"], result["linked"]), (0, 1))

    def test_long_developer_list_is_trimmed(self):
        developers = ", ".join(f"Studio Number {i}" for i in range(12))  # ~200 символів
        steam_app(1938090, "Call of Duty", developer=developers)
        steam_app(570, "Dota 2")
        import_steam_games(["1938090", "570"])
        game = Game.objects.get(steam_appid="1938090")
        self.assertLessEqual(len(game.developer), 100)
        self.assertTrue(game.developer.startswith("Studio Number 0"))
        self.assertTrue(Game.objects.filter(steam_appid="570").exists())  # решта імпорту не зупинилася

    def test_non_games_adult_and_blocked_are_skipped(self):
        steam_app(1, "Some DLC", app_type="dlc")
        steam_app(2, "Wallpaper Engine", genres="Casual, Utilities")
        steam_app(3, "Adult Game", adult=True)
        steam_app(4, "Deleted By Admin", blocked=True)
        for appid in (1, 2, 3, 4):
            self.own(self.alice_steam, appid, f"app {appid}")

        self.assertEqual(import_steam_games(["1", "2", "3", "4"])["created"], 0)
        self.assertFalse(Game.objects.exists())

    def test_existing_catalog_game_gets_steam_genres(self):
        game = self.make_game("Hades", steam_appid="1145360")
        steam_app(1145360, "Hades", genres="Action, Indie, RPG")
        import_steam_games(["1145360"])
        self.assertEqual(game_genres(game), {"Action", "Indie", "RPG"})

    def test_waiting_requests_are_auto_approved_with_notification(self):
        by_appid = GameRequest.objects.create(user=self.bob, title="Whatever", steam_appid="367520", status="pending", created_at=timezone.now())
        by_title = GameRequest.objects.create(user=self.alice, title="Hollow Knight", status="pending", created_at=timezone.now())
        steam_app(367520, "Hollow Knight")
        self.own(self.alice_steam, 367520, "Hollow Knight")

        import_steam_games(["367520"])

        for game_request in (by_appid, by_title):
            game_request.refresh_from_db()
            self.assertEqual(game_request.status, "approved")
        self.assertEqual(Notification.objects.filter(kind=Notification.GAME_APPROVED).count(), 2)

    def test_admin_delete_blocks_reimport(self):
        steam_app(413150, "Stardew Valley")
        self.own(self.alice_steam, 413150, "Stardew Valley")
        import_steam_games(["413150"])
        game = Game.objects.get(steam_appid="413150")

        self.login(self.make_user("admin", admin=True))
        self.client.post(reverse("library:admin_game_delete", args=[game.id]))
        import_steam_games(["413150"])

        self.assertFalse(Game.objects.filter(steam_appid="413150").exists())
        self.assertTrue(SteamApp.objects.get(appid="413150").blocked)

    def test_full_sync_adds_games_to_catalog(self):
        store = {"620": {"name": "Portal 2", "type": "game", "genres": [{"description": "Action"}],
                         "short_description": "<b>Puzzle</b> game", "developers": ["Valve"],
                         "release_date": {"date": "18 Apr, 2011"}}}

        def fake_fetch(appid, language):
            return store[str(appid)]

        with mock.patch("library.services.steam_service.get_owned_games",
                        return_value=[{"appid": 620, "name": "Portal 2", "playtime_forever": 300}]), \
                mock.patch("library.services.steam_service._fetch_app_data", side_effect=fake_fetch):
            result = sync_steam_library(self.alice, self.alice_steam)

        game = Game.objects.get(steam_appid="620")
        self.assertEqual((game.description, game.developer, str(game.release_date)), ("Puzzle game", "Valve", "2011-04-18"))
        self.assertEqual((result["catalog_added"], result["added_to_library_count"]), (1, 1))
        self.assertTrue(LibraryEntry.objects.filter(user=self.alice, game=game).exists())


class SteamLibraryPageTests(GameVaultTestCase):
    def setUp(self):
        self.alice = self.make_user("alice")
        account = self.make_steam_account(self.alice)
        self.make_steam_item(account, 1, "Wallpaper Engine", playtime=60)
        self.make_steam_item(account, 2, "Pending Game")
        steam_app(1, "Wallpaper Engine", genres="Utilities")
        self.login(self.alice)

    def test_notes_instead_of_suggest_button(self):
        response = self.client.get(reverse("library:steam_library"))
        self.assertContains(response, "Не гра — не в каталозі")
        self.assertContains(response, "Додається в каталог")
        self.assertNotContains(response, "Запропонувати")

    def test_launch_button_depends_on_recent_play(self):
        response = self.client.get(reverse("library:steam_library"))
        self.assertContains(response, "steam://nav/games/details/1")
        self.assertNotContains(response, "steam://run/1")
        ExternalLibraryItem.objects.filter(external_game_id="1").update(playtime_2weeks_minutes=30)
        self.assertContains(self.client.get(reverse("library:steam_library")), "steam://run/1")


class CoverFallbackTests(GameVaultTestCase):
    def test_steam_game_without_poster_uses_cdn_cover(self):
        self.make_game("Portal 2", steam_appid="620")
        self.assertContains(self.client.get(reverse("library:game_list")), "steam/apps/620/library_600x900.jpg")
