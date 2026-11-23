"""Смоук-тести сторінок: кожна рендериться в новому дизайні (base.html) і показує свої дані."""

from django.urls import reverse
from django.utils import timezone

from library.models import GameGenre, GameRequest, Genre, Review

from .base import GameVaultTestCase


class PageRenderTests(GameVaultTestCase):
    def setUp(self):
        self.admin = self.make_user("admin", admin=True)
        self.friend = self.make_user("friend")
        self.make_friends(self.admin, self.friend)

        self.genre = Genre.objects.create(name="Roguelike")
        self.unused_genre = Genre.objects.create(name="Unused")
        self.game = self.make_game("Hades", steam_appid="1145360")
        GameGenre.objects.create(game=self.game, genre=self.genre)
        self.unlinked = self.make_game("Unlinked Game")
        Review.objects.create(user=self.admin, game=self.game, score=9, text="Чудова", created_at=timezone.now())

        now = timezone.now()
        GameRequest.objects.create(user=self.friend, title="Pending Game", description="Опис", steam_appid="620",
                                   status="pending", created_at=now)
        GameRequest.objects.create(user=self.friend, title="Approved Game", status="approved", created_at=now,
                                   reviewed_at=now, moderator=self.admin)

        account = self.make_steam_account(self.admin)
        self.make_steam_item(account, 1145360, "Hades", playtime=600, playtime_2weeks=120)
        self.make_steam_item(account, 620, "Portal 2", playtime=300)
        friend_account = self.make_steam_account(self.friend, steam_id="76561197960287931")
        self.make_steam_item(friend_account, 620, "Portal 2", playtime=90, playtime_2weeks=60)

        self.login(self.admin)

    def assert_page(self, url, *texts):
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, url)
        self.assertTemplateUsed(response, "library/base.html")
        self.assertContains(response, "gv.css")
        for text in texts:
            self.assertContains(response, text)
        return response

    def test_user_pages(self):
        self.assert_page(reverse("library:edit_profile"), 'name="is_private"', 'name="show_activity"', "steam_admin")
        self.assert_page(reverse("library:my_reviews"), "Hades", "9/10")
        self.assert_page(reverse("library:request_game"), 'name="title"')
        self.assert_page(reverse("library:steam_library"), "Hades", "Portal 2", "Заявку подано")
        self.assert_page(reverse("library:user_steam_library", args=[self.friend.id]), "Portal 2")
        self.assert_page(reverse("library:feed"), "gv-np-card", "Portal 2", "friend")

    def test_profile_shows_favorite_game_and_top_genres(self):
        response = self.assert_page(reverse("library:profile"), "Улюблені жанри", "Roguelike", "gv-profile-head__backdrop")
        self.assertEqual(response.context["backdrop"]["title"], "Hades")
        self.assertEqual(response.context["top_genres"][0]["genre"], self.genre)
        self.assert_page(reverse("library:user_profile", args=[self.friend.id]), "gv-steam-card")

    def test_my_requests(self):
        self.login(self.friend)
        self.assert_page(reverse("library:my_requests"), "Pending Game", "gv-state--pending", "gv-state--approved")

    def test_admin_pages(self):
        response = self.assert_page(reverse("library:moderation"), "Pending Game", "Approved Game", "Roguelike")
        self.assertNotContains(response, self.friend.email)
        self.assert_page(reverse("library:admin_genre_list"), "Roguelike", "Unused")
        self.assert_page(reverse("library:admin_steam_matching"), "Unlinked Game", "Portal 2")
        self.assert_page(reverse("library:admin_game_add"), 'name="genres"')
        self.assert_page(reverse("library:admin_game_edit", args=[self.game.id]), 'value="Hades"', "checked")

    def test_no_access_page(self):
        self.login(self.friend)
        self.assert_page(reverse("library:moderation"), "Доступ заборонено")

    def test_auth_pages_keep_entered_username(self):
        self.client.logout()
        self.assert_page(reverse("library:register"), 'name="password_confirm"')
        response = self.client.post(reverse("library:login"), {"username": "admin", "password": "wrong"})
        self.assertContains(response, "Неправильний логін або пароль.")
        self.assertContains(response, 'value="admin"')
        self.assertNotContains(response, 'value="wrong"')
