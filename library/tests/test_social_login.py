"""Вхід і реєстрація через Steam/Google, прив'язка, способи входу."""

from unittest import mock

from django.test import override_settings
from django.urls import reverse

from library.models import ExternalAccount, User
from library.services.google_auth import GoogleError

from .base import GameVaultTestCase

STEAM_ID = "76561197960287930"
STEAM_PROFILE = {
    "steam_id": STEAM_ID, "username": "Gordon", "profile_url": f"https://steamcommunity.com/profiles/{STEAM_ID}",
    "avatar_url": "https://avatars.steamstatic.com/abc_full.jpg",
}
SYNC_RESULT = {"synced_count": 3, "added_to_library_count": 0, "removed_count": 0}


class SteamLoginTests(GameVaultTestCase):
    def setUp(self):
        patches = [
            mock.patch("library.views.steam.validate_steam_openid_response", return_value=True),
            mock.patch("library.views.steam.extract_steam_id_from_openid", return_value=STEAM_ID),
            mock.patch("library.views.steam.get_steam_profile", return_value=STEAM_PROFILE),
            mock.patch("library.views.steam.sync_steam_library", return_value=SYNC_RESULT),
            mock.patch("library.services.steam_service._download_image", return_value=None),
        ]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def callback(self):
        return self.client.get(reverse("library:steam_callback"))

    def test_guest_gets_new_account_in_one_click(self):
        response = self.callback()
        self.assertRedirects(response, reverse("library:profile"))
        user = User.objects.get(username="Gordon")
        self.assertEqual(self.client.session["library_user_id"], user.id)
        self.assertFalse(user.has_usable_password)
        self.assertIsNone(user.email)
        self.assertTrue(ExternalAccount.objects.filter(user=user, provider="steam", external_user_id=STEAM_ID).exists())

        profile = self.client.get(reverse("library:profile"))
        self.assertNotContains(profile, "None")

    def test_taken_username_gets_suffix(self):
        self.make_user("gordon")
        self.callback()
        self.assertTrue(User.objects.filter(username="Gordon_2").exists())

    def test_guest_with_linked_steam_logs_in(self):
        user = self.make_user("alice")
        self.make_steam_account(user, steam_id=STEAM_ID)
        self.assertRedirects(self.callback(), reverse("library:home"))
        self.assertEqual(self.client.session["library_user_id"], user.id)
        self.assertEqual(User.objects.count(), 1)

    def test_logged_in_user_links_steam(self):
        user = self.make_user("alice")
        self.login(user)
        self.assertRedirects(self.callback(), reverse("library:steam_library"))
        self.assertTrue(ExternalAccount.objects.filter(user=user, provider="steam").exists())

    def test_cannot_disconnect_only_login_method(self):
        self.callback()
        user = User.objects.get(username="Gordon")
        self.client.post(reverse("library:steam_disconnect"))
        self.assertTrue(ExternalAccount.objects.filter(user=user, provider="steam").exists())

    def test_steam_account_can_set_password_without_current(self):
        self.callback()
        user = User.objects.get(username="Gordon")
        self.client.post(reverse("library:edit_profile"), {
            "username": "Gordon", "email": "", "password": "lime-cartridge-42", "password_confirm": "lime-cartridge-42",
        })
        user.refresh_from_db()
        self.assertTrue(user.has_usable_password)


GOOGLE_INFO = {"sub": "g-123", "email": "alice@example.com", "email_verified": True, "name": "Alice G", "picture": None}


@override_settings(GOOGLE_CLIENT_ID="client-id", GOOGLE_CLIENT_SECRET="secret")
class GoogleLoginTests(GameVaultTestCase):
    def callback(self, info=GOOGLE_INFO):
        with mock.patch("library.views.google.fetch_google_user", return_value=dict(info)):
            return self.client.get(reverse("library:google_callback"))

    def test_connect_redirects_to_google_with_state_and_pkce(self):
        response = self.client.get(reverse("library:google_connect"))
        self.assertTrue(response["Location"].startswith("https://accounts.google.com/"))
        self.assertIn("code_challenge_method=S256", response["Location"])
        self.assertIn(self.client.session["google_oauth_state"], response["Location"])

    def test_bad_state_is_rejected(self):
        response = self.client.get(reverse("library:google_callback"), {"state": "forged", "code": "x"}, follow=True)
        self.assertIn("Сесія входу через Google застаріла. Спробуйте ще раз.", self.messages_of(response))
        self.assertNotIn("library_user_id", self.client.session)

    def test_new_user_with_verified_email(self):
        self.assertRedirects(self.callback(), reverse("library:profile"))
        user = User.objects.get(email="alice@example.com")
        self.assertTrue(user.is_email_verified)
        self.assertEqual(user.username, "Alice G")
        self.assertEqual(self.client.session["library_user_id"], user.id)

    def test_existing_verified_email_logs_in_and_links(self):
        alice = self.make_user("alice")
        self.assertRedirects(self.callback(), reverse("library:home"))
        self.assertEqual(self.client.session["library_user_id"], alice.id)
        self.assertTrue(ExternalAccount.objects.filter(user=alice, provider="google").exists())
        self.assertEqual(User.objects.count(), 1)

    def test_existing_unverified_email_is_not_taken_over(self):
        alice = self.make_user("alice", verified=False)
        response = self.callback()
        self.assertRedirects(response, reverse("library:login"))
        self.assertNotIn("library_user_id", self.client.session)
        self.assertFalse(ExternalAccount.objects.filter(user=alice, provider="google").exists())

    def test_google_linked_to_other_user_cannot_be_linked_again(self):
        bob = self.make_user("bob")
        ExternalAccount.objects.create(user=bob, provider="google", external_user_id="g-123")
        alice = self.make_user("alice")
        self.login(alice)
        self.callback()
        self.assertFalse(ExternalAccount.objects.filter(user=alice, provider="google").exists())

    def test_disconnect_respects_last_method(self):
        self.callback()
        user = User.objects.get(email="alice@example.com")
        self.client.post(reverse("library:google_disconnect"))
        self.assertTrue(ExternalAccount.objects.filter(user=user, provider="google").exists())

        alice = self.make_user("carol")
        ExternalAccount.objects.create(user=alice, provider="google", external_user_id="g-999")
        self.login(alice)  # має пароль і підтверджений email — Google можна відключити
        self.client.post(reverse("library:google_disconnect"))
        self.assertFalse(ExternalAccount.objects.filter(user=alice, provider="google").exists())

    @override_settings(GOOGLE_CLIENT_ID="", GOOGLE_CLIENT_SECRET="")
    def test_hidden_when_not_configured(self):
        self.assertNotContains(self.client.get(reverse("library:login")), "google/connect")


class FetchGoogleUserTests(GameVaultTestCase):
    def test_cancel_raises(self):
        from django.test import RequestFactory

        from library.services.google_auth import fetch_google_user

        request = RequestFactory().get("/", {"error": "access_denied"})
        request.session = {}
        with self.assertRaises(GoogleError):
            fetch_google_user(request)
