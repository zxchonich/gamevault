from django.test import Client
from django.urls import reverse
from django.utils import timezone

from library.models import GameRequest, LibraryEntry, Review, SocialConnection

from .base import GameVaultTestCase


class PostOnlyActionsTests(GameVaultTestCase):
    """Дії, що змінюють дані, не можна викликати GET-запитом (посиланням з чужого сайту)."""

    def setUp(self):
        self.user = self.make_user("alice")
        self.other = self.make_user("bob")
        self.game = self.make_game("Hades")
        self.login(self.user)

    def test_actions_reject_get(self):
        urls = [
            reverse("library:add_to_library", args=[self.game.id]),
            reverse("library:add_friend", args=[self.other.id]),
            reverse("library:accept_connection", args=[1]),
            reverse("library:reject_connection", args=[1]),
            reverse("library:approve_request", args=[1]),
            reverse("library:reject_request", args=[1]),
            reverse("library:logout"),
            reverse("library:steam_disconnect"),
            reverse("library:steam_sync_library"),
            reverse("library:steam_suggest_game", args=[730]),
            reverse("library:admin_steam_link", args=[self.game.id]),
            reverse("library:update_library_status", args=[1]),
            reverse("library:delete_library_entry", args=[1]),
            reverse("library:add_review", args=[self.game.id]),
            reverse("library:delete_connection", args=[1]),
            reverse("library:admin_game_delete", args=[self.game.id]),
            reverse("library:admin_review_delete", args=[1]),
            reverse("library:admin_genre_delete", args=[1]),
            reverse("library:dismiss_recommendation", args=[self.game.id]),
        ]
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 405)

        self.assertFalse(LibraryEntry.objects.filter(user=self.user).exists())
        self.assertFalse(SocialConnection.objects.exists())

    def test_csrf_token_required(self):
        client = self.login(self.user, Client(enforce_csrf_checks=True))

        response = client.post(reverse("library:add_to_library", args=[self.game.id]))

        self.assertEqual(response.status_code, 403)
        self.assertFalse(LibraryEntry.objects.filter(user=self.user).exists())


class AdminAccessTests(GameVaultTestCase):
    def setUp(self):
        self.user = self.make_user("alice")
        self.admin = self.make_user("root", admin=True)

    def test_admin_pages_forbidden_for_regular_user(self):
        self.login(self.user)
        for name in ["library:moderation", "library:admin_game_add", "library:admin_genre_list",
                     "library:admin_steam_matching"]:
            with self.subTest(page=name):
                response = self.client.get(reverse(name))
                self.assertTemplateUsed(response, "library/no_access.html")

    def test_regular_user_cannot_approve_request(self):
        request = GameRequest.objects.create(
            user=self.user, title="New game", status="pending", created_at=timezone.now()
        )
        self.login(self.user)

        self.client.post(reverse("library:approve_request", args=[request.id]))

        request.refresh_from_db()
        self.assertEqual(request.status, "pending")

    def test_admin_pages_open_for_admin(self):
        self.login(self.admin)
        for name in ["library:moderation", "library:admin_game_add", "library:admin_genre_list",
                     "library:admin_steam_matching"]:
            with self.subTest(page=name):
                response = self.client.get(reverse(name))
                self.assertEqual(response.status_code, 200)
                self.assertTemplateNotUsed(response, "library/no_access.html")


class OwnershipTests(GameVaultTestCase):
    def setUp(self):
        self.alice = self.make_user("alice")
        self.bob = self.make_user("bob")
        self.game = self.make_game("Hades")

    def test_cannot_delete_someone_elses_library_entry(self):
        entry = self.make_entry(self.bob, self.game)
        self.login(self.alice)

        response = self.client.post(reverse("library:delete_library_entry", args=[entry.id]))

        self.assertEqual(response.status_code, 404)
        self.assertTrue(LibraryEntry.objects.filter(id=entry.id).exists())

    def test_only_receiver_can_accept_friend_request(self):
        carol = self.make_user("carol")
        connection = self.make_friends(self.alice, self.bob, status="pending")
        self.login(carol)

        self.client.post(reverse("library:accept_connection", args=[connection.id]))

        connection.refresh_from_db()
        self.assertEqual(connection.status, "pending")

    def test_review_delete_ignores_external_next(self):
        review = Review.objects.create(user=self.alice, game=self.game, score=8, created_at=timezone.now())
        self.login(self.alice)

        response = self.client.post(
            reverse("library:admin_review_delete", args=[review.id]), {"next": "https://evil.example/"}
        )

        self.assertRedirects(response, reverse("library:game_detail", args=[self.game.id]),
                             fetch_redirect_response=False)

    def test_review_delete_allows_local_next(self):
        review = Review.objects.create(user=self.alice, game=self.game, score=8, created_at=timezone.now())
        self.login(self.alice)

        response = self.client.post(
            reverse("library:admin_review_delete", args=[review.id]), {"next": reverse("library:my_reviews")}
        )

        self.assertRedirects(response, reverse("library:my_reviews"), fetch_redirect_response=False)


class AnonymousAccessTests(GameVaultTestCase):
    def test_anonymous_actions_and_admin_pages_redirect_to_login(self):
        target = self.make_user("bob")
        game = self.make_game("Hades")

        for url in [reverse("library:add_friend", args=[target.id]),
                    reverse("library:add_to_library", args=[game.id])]:
            with self.subTest(url=url):
                self.assertRedirects(self.client.post(url), reverse("library:login"))

        for name in ["library:moderation", "library:admin_game_add", "library:admin_steam_matching"]:
            with self.subTest(page=name):
                self.assertRedirects(self.client.get(reverse(name)), reverse("library:login"))

    def test_cannot_befriend_yourself(self):
        alice = self.make_user("alice")
        self.login(alice)

        response = self.client.post(reverse("library:add_friend", args=[alice.id]), follow=True)

        self.assertIn("Не можна додати в друзі самого себе.", self.messages_of(response))



class EmailPrivacyTests(GameVaultTestCase):
    def test_other_users_emails_are_not_shown(self):
        alice, bob = self.make_user("alice"), self.make_user("bob")
        self.make_friends(alice, bob)
        self.make_entry(bob, self.make_game("Hades"))
        self.login(alice)

        pages = ["library:home", "library:user_list", "library:friends", "library:feed"]
        urls = [reverse(name) for name in pages] + [
            reverse("library:user_profile", args=[bob.id]),
            reverse("library:user_library", args=[bob.id]),
        ]
        for url in urls:
            with self.subTest(url=url):
                self.assertNotContains(self.client.get(url), bob.email)

        self.assertContains(self.client.get(reverse("library:profile")), alice.email)
