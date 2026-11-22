from django.urls import reverse
from django.utils import timezone

from library.models import GameGenre, Genre, LibraryEntry, Review, SocialConnection

from .base import GameVaultTestCase


class LibraryTests(GameVaultTestCase):
    def setUp(self):
        self.user = self.make_user("alice")
        self.game = self.make_game("Hades")
        self.login(self.user)

    def test_add_to_library_creates_planned_entry_once(self):
        url = reverse("library:add_to_library", args=[self.game.id])

        self.client.post(url)
        self.client.post(url)

        entries = LibraryEntry.objects.filter(user=self.user, game=self.game)
        self.assertEqual(entries.count(), 1)
        self.assertEqual(entries.get().status, "planned")

    def test_update_status_accepts_only_known_statuses(self):
        entry = self.make_entry(self.user, self.game)
        url = reverse("library:update_library_status", args=[entry.id])

        self.client.post(url, {"status": "completed"})
        entry.refresh_from_db()
        self.assertEqual(entry.status, "completed")

        self.client.post(url, {"status": "hacked"})
        entry.refresh_from_db()
        self.assertEqual(entry.status, "completed")

    def test_delete_entry_also_deletes_review(self):
        entry = self.make_entry(self.user, self.game)
        Review.objects.create(user=self.user, game=self.game, score=9, created_at=timezone.now())

        self.client.post(reverse("library:delete_library_entry", args=[entry.id]))

        self.assertFalse(LibraryEntry.objects.filter(id=entry.id).exists())
        self.assertFalse(Review.objects.filter(user=self.user, game=self.game).exists())

    def test_review_score_validation(self):
        url = reverse("library:add_review", args=[self.game.id])

        self.client.post(url, {"score": "11", "text": "too high"})
        self.assertFalse(Review.objects.exists())

        self.client.post(url, {"score": "7", "text": "ok"})
        self.client.post(url, {"score": "9", "text": "better"})
        review = Review.objects.get(user=self.user, game=self.game)
        self.assertEqual((review.score, review.text), (9, "better"))


class GameGenreSchemaTests(GameVaultTestCase):
    """game_genres має складений первинний ключ — перевіряємо, що ORM із ним працює."""

    def test_create_filter_and_delete_game_genres(self):
        game = self.make_game("Hades")
        rogue = Genre.objects.create(name="Roguelike")
        action = Genre.objects.create(name="Action")

        GameGenre.objects.create(game=game, genre=rogue)
        GameGenre.objects.create(game=game, genre=action)
        self.assertEqual(set(Genre.objects.filter(game_genres__game=game).values_list("name", flat=True)),
                         {"Roguelike", "Action"})

        GameGenre.objects.filter(game=game).delete()
        self.assertFalse(GameGenre.objects.filter(game=game).exists())


class FriendsAndPrivacyTests(GameVaultTestCase):
    def setUp(self):
        self.alice = self.make_user("alice")
        self.bob = self.make_user("bob", private=True)

    def test_friend_request_flow(self):
        self.login(self.alice)
        self.client.post(reverse("library:add_friend", args=[self.bob.id]))
        connection = SocialConnection.objects.get(sender=self.alice, receiver=self.bob)
        self.assertEqual(connection.status, "pending")

        self.client.post(reverse("library:add_friend", args=[self.bob.id]))
        self.assertEqual(SocialConnection.objects.count(), 1)

        self.login(self.bob)
        self.client.post(reverse("library:accept_connection", args=[connection.id]))
        connection.refresh_from_db()
        self.assertEqual(connection.status, "accepted")

    def test_private_profile_hidden_from_non_friend(self):
        self.login(self.alice)

        for name in ["library:user_profile", "library:user_library"]:
            with self.subTest(page=name):
                response = self.client.get(reverse(name, args=[self.bob.id]))
                self.assertTemplateUsed(response, "library/private_profile.html")

    def test_private_profile_visible_to_friend(self):
        self.make_friends(self.alice, self.bob)
        self.login(self.alice)

        response = self.client.get(reverse("library:user_profile", args=[self.bob.id]))

        self.assertTemplateUsed(response, "library/user_profile.html")


class PagesSmokeTests(GameVaultTestCase):
    def test_main_pages_render(self):
        user = self.make_user("alice")
        other = self.make_user("bob")
        game = self.make_game("Hades")
        self.make_entry(user, game)
        self.login(user)

        pages = [
            reverse("library:home"),
            reverse("library:game_list"),
            reverse("library:game_detail", args=[game.id]),
            reverse("library:my_library"),
            reverse("library:my_reviews"),
            reverse("library:my_requests"),
            reverse("library:request_game"),
            reverse("library:recommendations"),
            reverse("library:friends"),
            reverse("library:user_list"),
            reverse("library:profile"),
            reverse("library:edit_profile"),
            reverse("library:user_profile", args=[other.id]),
            reverse("library:user_library", args=[other.id]),
            reverse("library:steam_library"),
        ]
        for url in pages:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_anonymous_redirected_to_login(self):
        for name in ["library:my_library", "library:profile", "library:steam_library", "library:friends"]:
            with self.subTest(page=name):
                self.assertRedirects(self.client.get(reverse(name)), reverse("library:login"))
