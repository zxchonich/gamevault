from io import StringIO

from django.contrib.auth.hashers import check_password
from django.core.management import call_command
from django.urls import reverse

from library.models import User

from .base import DEFAULT_PASSWORD, USER_ROLE_ID, GameVaultTestCase


class RegistrationTests(GameVaultTestCase):
    def register(self, **overrides):
        data = {
            "username": "newbie",
            "email": "newbie@example.com",
            "password": "pass-12345",
            "password_confirm": "pass-12345",
        }
        data.update(overrides)
        return self.client.post(reverse("library:register"), data)

    def test_register_creates_user_with_hashed_password_and_logs_in(self):
        self.client.get(reverse("library:register"))
        old_key = self.client.session.session_key

        response = self.register()

        self.assertRedirects(response, reverse("library:profile"))
        user = User.objects.get(username="newbie")
        self.assertEqual(user.role_id, USER_ROLE_ID)
        self.assertTrue(check_password("pass-12345", user.password_hash))
        self.assertEqual(self.client.session["library_user_id"], user.id)
        self.assertNotEqual(self.client.session.session_key, old_key)

    def test_password_mismatch(self):
        response = self.register(password_confirm="other")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["error"], "Паролі не збігаються.")
        self.assertFalse(User.objects.filter(username="newbie").exists())

    def test_duplicate_username(self):
        self.make_user("newbie")

        response = self.register(email="another@example.com")

        self.assertIn("логіном", response.context["error"])
        self.assertEqual(User.objects.filter(username="newbie").count(), 1)


class LoginLogoutTests(GameVaultTestCase):
    def setUp(self):
        self.user = self.make_user("alice")

    def test_login_success_rotates_session(self):
        self.client.get(reverse("library:login"))
        old_key = self.client.session.session_key

        response = self.client.post(
            reverse("library:login"), {"username": "alice", "password": DEFAULT_PASSWORD}
        )

        self.assertRedirects(response, reverse("library:home"))
        self.assertEqual(self.client.session["library_user_id"], self.user.id)
        self.assertNotEqual(self.client.session.session_key, old_key)

    def test_login_wrong_password(self):
        response = self.client.post(reverse("library:login"), {"username": "alice", "password": "nope"})

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("library_user_id", self.client.session)

    def test_plaintext_password_is_not_accepted(self):
        User.objects.filter(id=self.user.id).update(password_hash="plain-text")

        self.client.post(reverse("library:login"), {"username": "alice", "password": "plain-text"})

        self.assertNotIn("library_user_id", self.client.session)

    def test_logout_requires_post_and_flushes_session(self):
        self.login(self.user)

        self.assertEqual(self.client.get(reverse("library:logout")).status_code, 405)
        self.assertIn("library_user_id", self.client.session)

        self.client.post(reverse("library:logout"))
        self.assertNotIn("library_user_id", self.client.session)


class HashPlainPasswordsCommandTests(GameVaultTestCase):
    def setUp(self):
        self.hashed = self.make_user("hashed")
        self.plain = self.make_user("plain")
        self.empty = self.make_user("empty")
        User.objects.filter(id=self.plain.id).update(password_hash="qwerty")
        User.objects.filter(id=self.empty.id).update(password_hash="")

    def test_dry_run_changes_nothing(self):
        call_command("hash_plain_passwords", "--dry-run", stdout=StringIO())

        self.assertEqual(User.objects.get(id=self.plain.id).password_hash, "qwerty")

    def test_hashes_plain_skips_empty_keeps_hashed(self):
        hashed_before = User.objects.get(id=self.hashed.id).password_hash

        call_command("hash_plain_passwords", stdout=StringIO())

        self.assertTrue(check_password("qwerty", User.objects.get(id=self.plain.id).password_hash))
        self.assertEqual(User.objects.get(id=self.empty.id).password_hash, "")
        self.assertEqual(User.objects.get(id=self.hashed.id).password_hash, hashed_before)
