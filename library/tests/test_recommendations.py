from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from library.models import DismissedRecommendation, GameGenre, Genre, Review
from library.services.recommendations import build_recommendations, review_weight, steam_weight

from .base import GameVaultTestCase


class WeightTests(GameVaultTestCase):
    def test_review_weight(self):
        self.assertEqual([review_weight(s) for s in (10, 8, 7, 5, 4, 1)], [3, 1, 0, 0, -1, -4])

    def test_format_number(self):
        from library.services.recommendations import format_number
        self.assertEqual([format_number(x) for x in (9.0, 9.5, 8.25)], ["9", "9,5", "8,2"])

    def test_steam_weight_is_logarithmic_and_capped(self):
        self.assertEqual(steam_weight(0), 0)
        two_hours, two_hundred_hours = steam_weight(120), steam_weight(200 * 60)
        self.assertLess(two_hours, two_hundred_hours)
        self.assertLess(two_hundred_hours / two_hours, 10)
        self.assertLessEqual(steam_weight(10_000 * 60), 4)
        self.assertEqual(steam_weight(120, minutes_2weeks=30), two_hours + 0.5)


class RecommendationTestCase(GameVaultTestCase):
    def setUp(self):
        self.user = self.make_user("alice")
        self.genres = {name: Genre.objects.create(name=name) for name in ("Roguelike", "Action", "Horror", "Puzzle")}

    def game(self, title, *genre_names, appid=None):
        game = self.make_game(title, steam_appid=appid)
        for name in genre_names:
            GameGenre.objects.create(game=game, genre=self.genres[name])
        return game

    def review(self, user, game, score):
        return Review.objects.create(user=user, game=game, score=score, created_at=timezone.now())

    def recommended(self, user=None, **kwargs):
        result = build_recommendations(user or self.user, **kwargs)
        return {r.game.title: r for r in result.recommendations}, result


class RecommendationScoringTests(RecommendationTestCase):
    def test_liked_genre_beats_disliked_genre(self):
        hades = self.game("Hades", "Roguelike", "Action")
        self.make_entry(self.user, hades, status="completed")
        self.review(self.user, hades, 10)
        horror = self.game("Outlast", "Horror")
        self.make_entry(self.user, horror, status="dropped")
        self.review(self.user, horror, 2)

        self.game("Dead Cells", "Roguelike", "Action")
        self.game("Amnesia", "Horror")

        recs, result = self.recommended()

        self.assertFalse(result.is_fallback)
        self.assertIn("Dead Cells", recs)
        self.assertNotIn("Amnesia", recs)
        self.assertIn("Схожа на «Hades» з вашої бібліотеки", recs["Dead Cells"].reasons)

    def test_steam_playtime_shapes_profile(self):
        account = self.make_steam_account(self.user)
        self.game("Hades", "Roguelike", appid="1145360")
        self.make_steam_item(account, 1145360, "Hades", playtime=50 * 60)
        self.game("Dead Cells", "Roguelike")
        self.game("Tetris", "Puzzle")

        recs, result = self.recommended()

        self.assertTrue(result.has_steam_signals)
        self.assertNotIn("Hades", recs)  # уже є в Steam
        self.assertIn("Dead Cells", recs)
        self.assertNotIn("Tetris", recs)

    def test_friends_add_points_and_reasons(self):
        bob = self.make_user("bob")
        self.make_friends(self.user, bob)
        self.make_entry(self.user, self.game("Hades", "Roguelike"), status="completed")
        tetris = self.game("Tetris", "Puzzle")
        self.make_entry(bob, tetris, status="completed")
        self.review(bob, tetris, 9)

        recs, _ = self.recommended()

        reasons = recs["Tetris"].reasons
        self.assertIn("Є у bob", reasons)
        self.assertIn("Друзі оцінили в середньому 9/10", reasons)
        self.assertGreater(recs["Tetris"].friend_points, 0)

    def test_non_friend_activity_is_ignored(self):
        stranger = self.make_user("stranger")
        self.make_entry(self.user, self.game("Hades", "Roguelike"), status="completed")
        tetris = self.game("Tetris", "Puzzle")
        self.make_entry(stranger, tetris)

        recs, _ = self.recommended()

        self.assertNotIn("Є у stranger", recs.get("Tetris").reasons if "Tetris" in recs else [])

    def test_excludes_library_steam_and_dismissed_games(self):
        account = self.make_steam_account(self.user)
        hades = self.game("Hades", "Roguelike")
        self.make_entry(self.user, hades, status="completed")
        self.game("Dead Cells", "Roguelike", appid="588650")
        self.make_steam_item(account, 588650, "Dead Cells")
        rogue = self.game("Rogue Legacy", "Roguelike")
        DismissedRecommendation.objects.create(user=self.user, game=rogue, created_at=timezone.now())
        self.game("Slay the Spire", "Roguelike")

        recs, _ = self.recommended()

        self.assertEqual(set(recs), {"Slay the Spire"})

    def test_rating_is_smoothed_by_review_count(self):
        reviewers = [self.make_user(f"r{i}") for i in range(6)]
        one_review = self.game("One Ten", "Puzzle")
        many_reviews = self.game("Many Nines", "Puzzle")
        self.review(reviewers[0], one_review, 10)
        for reviewer in reviewers:
            self.review(reviewer, many_reviews, 9)

        recs, _ = self.recommended()

        self.assertGreater(recs["Many Nines"].quality_points, recs["One Ten"].quality_points)

    def test_fallback_for_user_without_data(self):
        popular = self.game("Popular", "Action")
        for name in ("u1", "u2"):
            other = self.make_user(name)
            self.make_entry(other, popular)
            self.review(other, popular, 9)
        self.game("Unknown", "Puzzle")

        recs, result = self.recommended()

        self.assertTrue(result.is_fallback)
        self.assertEqual(list(recs), ["Popular"])
        self.assertIn("Популярна в GameVault: у 2 бібліотеках", recs["Popular"].reasons)

    def test_limit(self):
        self.make_entry(self.user, self.game("Hades", "Roguelike"), status="completed")
        for i in range(5):
            self.game(f"Rogue {i}", "Roguelike")

        recs, _ = self.recommended(limit=3)

        self.assertEqual(len(recs), 3)

    def test_query_count_does_not_grow_with_catalog(self):
        bob = self.make_user("bob")
        self.make_friends(self.user, bob)
        self.make_entry(self.user, self.game("Hades", "Roguelike"), status="completed")

        def count_queries():
            with CaptureQueriesContext(connection) as ctx:
                build_recommendations(self.user)
            return len(ctx.captured_queries)

        small = count_queries()
        for i in range(10):
            game = self.game(f"Game {i}", "Roguelike", "Action")
            self.make_entry(bob, game)
            self.review(bob, game, 8)

        self.assertEqual(count_queries(), small)


class RecommendationViewsTests(RecommendationTestCase):
    def setUp(self):
        super().setUp()
        self.make_entry(self.user, self.game("Hades", "Roguelike"), status="completed")
        self.dead_cells = self.game("Dead Cells", "Roguelike")
        self.login(self.user)

    def test_page_shows_reasons_and_does_not_write(self):
        with CaptureQueriesContext(connection) as ctx:
            response = self.client.get(reverse("library:recommendations"))

        self.assertContains(response, "Схожа на «Hades» з вашої бібліотеки")
        writes = [q["sql"] for q in ctx.captured_queries
                  if q["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))
                  and "django_session" not in q["sql"]]
        self.assertEqual(writes, [])

    def test_dismiss_and_restore(self):
        dismiss = reverse("library:dismiss_recommendation", args=[self.dead_cells.id])
        self.assertEqual(self.client.get(dismiss).status_code, 405)

        self.client.post(dismiss)
        self.client.post(dismiss)
        self.assertEqual(DismissedRecommendation.objects.filter(user=self.user).count(), 1)

        response = self.client.get(reverse("library:recommendations"))
        self.assertNotIn(self.dead_cells, [r.game for r in response.context["recommendations"]])
        self.assertEqual([d.game for d in response.context["dismissed"]], [self.dead_cells])

        self.client.post(reverse("library:restore_recommendation", args=[self.dead_cells.id]))
        self.assertFalse(DismissedRecommendation.objects.filter(user=self.user).exists())

    def test_home_shows_top_recommendations(self):
        response = self.client.get(reverse("library:home"))

        self.assertContains(response, "Рекомендовано для вас")
        self.assertEqual([r.game for r in response.context["home_recommendations"]], [self.dead_cells])

    def test_deleting_game_removes_dismissed_rows(self):
        admin = self.make_user("root", admin=True)
        DismissedRecommendation.objects.create(user=self.user, game=self.dead_cells, created_at=timezone.now())
        self.login(admin)

        self.client.post(reverse("library:admin_game_delete", args=[self.dead_cells.id]))

        self.assertFalse(DismissedRecommendation.objects.exists())


class SteamOnlyGamesTests(RecommendationTestCase):
    """Steam-ігри поза каталогом впливають на смаки через жанри Steam Store."""

    def steam_app(self, appid, *genres):
        from library.models import SteamApp
        SteamApp.objects.create(appid=str(appid), name=f"App {appid}", genres=", ".join(genres),
                                fetched_at=timezone.now())

    def test_played_steam_game_outside_catalog_shapes_profile(self):
        account = self.make_steam_account(self.user)
        self.make_steam_item(account, 578080, "PUBG", playtime=300 * 60)
        self.steam_app(578080, "Action", "Free To Play")
        self.game("Doom", "Action")
        self.game("Tetris", "Puzzle")

        recs, result = self.recommended()

        self.assertFalse(result.is_fallback)
        self.assertTrue(result.has_steam_signals)
        self.assertIn("Doom", recs)
        self.assertNotIn("Tetris", recs)
        self.assertIn("Схожа на «PUBG» з вашого Steam", recs["Doom"].reasons)

    def test_unplayed_or_unknown_steam_games_are_ignored(self):
        account = self.make_steam_account(self.user)
        self.make_steam_item(account, 1, "Never played", playtime=0)
        self.steam_app(1, "Action")
        self.make_steam_item(account, 2, "No store data", playtime=600)
        self.game("Doom", "Action")

        _, result = self.recommended()

        self.assertTrue(result.is_fallback)

    def test_mixed_sources_in_reason(self):
        account = self.make_steam_account(self.user)
        hades = self.game("Hades", "Action")
        self.make_entry(self.user, hades, status="completed")
        self.review(self.user, hades, 10)
        self.make_steam_item(account, 578080, "PUBG", playtime=50 * 60)
        self.steam_app(578080, "Action")
        self.game("Doom", "Action")

        recs, _ = self.recommended()

        self.assertIn("Схожа на «Hades» та «PUBG» з ваших ігор", recs["Doom"].reasons)

    def test_source_label_counts_hidden_titles(self):
        account = self.make_steam_account(self.user)
        hades = self.game("Hades", "Action")
        dead_cells = self.game("Dead Cells", "Action")
        for game in (hades, dead_cells):
            self.make_entry(self.user, game, status="completed")
            self.review(self.user, game, 10)
        self.make_steam_item(account, 578080, "PUBG", playtime=60)
        self.steam_app(578080, "Action")
        self.game("Doom", "Action")

        recs, _ = self.recommended()

        self.assertIn("Схожа на «Dead Cells» та «Hades» і ще 1 з ваших ігор", recs["Doom"].reasons)

