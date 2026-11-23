"""Безпека акаунта й файлів: зміна пароля, сила пароля, обмеження входу, прибирання файлів,
джерела постерів, сторінка 404."""

import shutil
import tempfile

from django.contrib.auth.hashers import check_password
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.test import Client, override_settings
from django.urls import reverse

from library.forms import password_problem
from library.models import User
from library.services.steam_service import is_steam_image_url

from .base import DEFAULT_PASSWORD, GameVaultTestCase

def make_png():
    """Справжній PNG 1×1 (Pillow), щоб ImageField прийняв файл."""
    import io

    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (1, 1), (200, 240, 49)).save(buffer, format="PNG")
    return buffer.getvalue()


PNG_1PX = make_png()


class PasswordChangeTests(GameVaultTestCase):
    def setUp(self):
        self.user = self.make_user("alice")
        self.login(self.user)
        self.other_device = self.login(self.user, Client())

    def change(self, **overrides):
        data = {
            "username": "alice", "email": "alice@example.com", "current_password": DEFAULT_PASSWORD,
            "password": "brand-new-pass-1", "password_confirm": "brand-new-pass-1",
        }
        data.update(overrides)
        return self.client.post(reverse("library:edit_profile"), data)

    def test_change_keeps_this_session_and_logs_out_others(self):
        self.assertRedirects(self.change(), reverse("library:profile"))
        self.user.refresh_from_db()
        self.assertTrue(check_password("brand-new-pass-1", self.user.password_hash))

        self.assertEqual(self.client.get(reverse("library:profile")).status_code, 200)
        self.assertRedirects(self.other_device.get(reverse("library:profile")), reverse("library:login"))

    def test_wrong_current_password_changes_nothing(self):
        response = self.change(current_password="wrong")
        self.assertEqual(response.context["error"], "Щоб змінити пароль, правильно вкажіть поточний.")
        self.user.refresh_from_db()
        self.assertTrue(check_password(DEFAULT_PASSWORD, self.user.password_hash))

    def test_profile_save_without_password_keeps_sessions(self):
        self.change(current_password="", password="", password_confirm="")
        self.assertEqual(self.other_device.get(reverse("library:profile")).status_code, 200)


class PasswordStrengthTests(GameVaultTestCase):
    def test_rules(self):
        self.assertEqual(password_problem("short1"), "Пароль має містити щонайменше 8 символів.")
        self.assertEqual(password_problem("1234567890"), "Пароль не може складатися лише з цифр.")
        self.assertEqual(password_problem("my-alice-pass", "alice"), "Пароль не повинен містити логін.")
        self.assertEqual(password_problem("password1"), "Цей пароль занадто поширений — придумайте складніший.")
        self.assertIsNone(password_problem("lime-cartridge-42", "alice"))

    def test_register_rejects_weak_password(self):
        response = self.client.post(reverse("library:register"), {
            "username": "newbie", "email": "newbie@example.com", "password": "123", "password_confirm": "123",
        })
        self.assertEqual(response.context["error"], "Пароль має містити щонайменше 8 символів.")
        self.assertFalse(User.objects.filter(username="newbie").exists())


class LoginThrottleTests(GameVaultTestCase):
    def setUp(self):
        self.user = self.make_user("alice")

    def attempt(self, password, username="alice"):
        return self.client.post(reverse("library:login"), {"username": username, "password": password})

    def test_locks_after_five_failures_even_for_correct_password(self):
        for _ in range(5):
            self.assertEqual(self.attempt("wrong").status_code, 200)
        response = self.attempt(DEFAULT_PASSWORD)
        self.assertEqual(response.status_code, 429)
        self.assertContains(response, "Забагато невдалих спроб", status_code=429)
        self.assertNotIn("library_user_id", self.client.session)

    def test_success_resets_counter(self):
        for _ in range(4):
            self.attempt("wrong")
        self.assertRedirects(self.attempt(DEFAULT_PASSWORD), reverse("library:home"))
        self.client.post(reverse("library:logout"))
        for _ in range(4):
            self.attempt("wrong")
        self.assertRedirects(self.attempt(DEFAULT_PASSWORD), reverse("library:home"))

    def test_other_username_is_not_locked(self):
        self.make_user("bob")
        for _ in range(5):
            self.attempt("wrong")
        self.assertRedirects(self.attempt(DEFAULT_PASSWORD, username="bob"), reverse("library:home"))


class FileCleanupTests(GameVaultTestCase):
    def setUp(self):
        self.media = tempfile.mkdtemp()
        self.override = override_settings(MEDIA_ROOT=self.media)
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.addCleanup(shutil.rmtree, self.media, ignore_errors=True)

    def test_new_avatar_removes_old_file(self):
        user = self.make_user("alice")
        user.avatar.save("old.png", ContentFile(PNG_1PX))
        old_name = user.avatar.name
        self.login(user)

        upload = ContentFile(PNG_1PX, name="new.png")
        self.client.post(reverse("library:edit_profile"), {
            "username": "alice", "email": "alice@example.com", "avatar": upload,
        })
        user.refresh_from_db()
        self.assertNotEqual(user.avatar.name, old_name)
        self.assertFalse(default_storage.exists(old_name))
        self.assertTrue(default_storage.exists(user.avatar.name))

    def test_game_delete_removes_poster(self):
        admin = self.make_user("admin", admin=True)
        game = self.make_game("Hades")
        game.poster.save("hades.png", ContentFile(PNG_1PX))
        name = game.poster.name
        self.login(admin)
        self.client.post(reverse("library:admin_game_delete", args=[game.id]))
        self.assertFalse(default_storage.exists(name))

    def test_admin_rejects_non_image_poster(self):
        admin = self.make_user("admin", admin=True)
        self.login(admin)
        response = self.client.post(reverse("library:admin_game_add"), {
            "title": "Fake", "poster": ContentFile(b"not an image", name="x.png"),
        }, follow=True)
        self.assertIn("Постер має бути зображенням (JPG, PNG, WebP).", self.messages_of(response))


class SteamImageSourceTests(GameVaultTestCase):
    def test_only_https_steam_hosts(self):
        self.assertTrue(is_steam_image_url("https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/1/header.jpg"))
        self.assertTrue(is_steam_image_url("https://cdn.cloudflare.steamstatic.com/steam/apps/1/header.jpg"))
        self.assertFalse(is_steam_image_url("http://cdn.cloudflare.steamstatic.com/steam/apps/1/header.jpg"))
        self.assertFalse(is_steam_image_url("https://steamstatic.com.evil.example/x.jpg"))
        self.assertFalse(is_steam_image_url("http://127.0.0.1:8000/admin/"))


class NotFoundPageTests(GameVaultTestCase):
    def test_404_uses_site_design(self):
        response = self.client.get("/no-such-page/")
        self.assertEqual(response.status_code, 404)
        self.assertTemplateUsed(response, "404.html")
        self.assertContains(response, "Сторінку не знайдено", status_code=404)
        self.assertContains(response, "gv.css", status_code=404)
