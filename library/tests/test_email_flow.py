"""Підтвердження email, вхід без підтвердження, зміна email, скидання пароля."""

import re
from io import StringIO

from django.contrib.auth.hashers import check_password
from django.core import mail
from django.core.management import call_command
from django.urls import reverse

from library.models import User
from library.services.account_email import make_reset_token, make_verify_token

from .base import DEFAULT_PASSWORD, GameVaultTestCase

LINK_RE = re.compile(r"http://testserver(/\S+)")


def link_from(message):
    return LINK_RE.search(message.body).group(1)


class RegistrationVerificationTests(GameVaultTestCase):
    def register(self):
        return self.client.post(reverse("library:register"), {
            "username": "newbie", "email": "newbie@example.com",
            "password": "lime-cartridge-42", "password_confirm": "lime-cartridge-42",
        })

    def test_register_sends_letter_and_link_verifies_and_logs_in(self):
        self.assertRedirects(self.register(), reverse("library:verify_pending"))
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["newbie@example.com"])
        self.assertContains(self.client.get(reverse("library:verify_pending")), "newbie@example.com")

        response = self.client.get(link_from(mail.outbox[0]))
        self.assertRedirects(response, reverse("library:profile"))
        user = User.objects.get(username="newbie")
        self.assertIsNotNone(user.email_verified_at)
        self.assertEqual(self.client.session["library_user_id"], user.id)

    def test_double_submit_leads_to_verify_page_not_error(self):
        self.register()
        self.client.session.flush()
        response = self.register()  # та сама форма вдруге (подвійний клік / інша вкладка)
        self.assertRedirects(response, reverse("library:verify_pending"))
        self.assertEqual(User.objects.filter(username="newbie").count(), 1)

    def test_letter_has_explicit_message_id(self):
        with self.settings(DEFAULT_FROM_EMAIL="GameVault <noreply@gamevault.test>"):
            self.register()
        self.assertIn("@gamevault.test>", mail.outbox[0].extra_headers["Message-ID"])

    def test_unverified_login_shows_verify_page_and_stays_guest(self):
        self.make_user("alice", verified=False)
        response = self.client.post(reverse("library:login"), {"username": "alice", "password": DEFAULT_PASSWORD})
        self.assertRedirects(response, reverse("library:verify_pending"))
        self.assertNotIn("library_user_id", self.client.session)
        self.assertRedirects(self.client.get(reverse("library:profile")), reverse("library:login"))
        self.assertEqual(len(mail.outbox), 1)

    def test_resend_is_rate_limited(self):
        self.register()
        self.client.post(reverse("library:verify_pending"))
        self.assertEqual(len(mail.outbox), 1)  # друга спроба одразу — без листа

    def test_login_by_email(self):
        self.make_user("alice")
        response = self.client.post(reverse("library:login"), {"username": "ALICE@example.com", "password": DEFAULT_PASSWORD})
        self.assertRedirects(response, reverse("library:home"))

    def test_bad_and_foreign_tokens(self):
        self.assertEqual(self.client.get(reverse("library:verify_email", args=["garbage"])).status_code, 400)
        self.assertEqual(self.client.get(reverse("library:password_reset_confirm", args=["garbage"])).status_code, 400)


class EmailChangeTests(GameVaultTestCase):
    def setUp(self):
        self.user = self.make_user("alice")
        self.login(self.user)

    def save(self, email):
        return self.client.post(reverse("library:edit_profile"), {"username": "alice", "email": email})

    def test_new_email_applies_only_after_confirmation(self):
        self.save("new@example.com")
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "alice@example.com")
        self.assertEqual(mail.outbox[0].to, ["new@example.com"])

        self.client.get(link_from(mail.outbox[0]))
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "new@example.com")
        self.assertIsNotNone(self.user.email_verified_at)

    def test_confirmation_fails_if_address_taken_meanwhile(self):
        self.save("taken@example.com")
        self.make_user("bob").__class__.objects.filter(username="bob").update(email="taken@example.com")
        self.assertEqual(self.client.get(link_from(mail.outbox[0])).status_code, 400)
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "alice@example.com")

    def test_password_only_account_cannot_drop_email(self):
        response = self.save("")
        self.assertEqual(response.context["error"], "Логін та email не можуть бути порожніми.")


class PasswordResetTests(GameVaultTestCase):
    def setUp(self):
        self.user = self.make_user("alice")

    def test_full_flow_and_link_is_single_use(self):
        self.client.post(reverse("library:password_reset"), {"email": "alice@example.com"})
        link = link_from(mail.outbox[0])
        response = self.client.post(link, {"password": "fresh-pass-777", "password_confirm": "fresh-pass-777"})
        self.assertRedirects(response, reverse("library:profile"))
        self.user.refresh_from_db()
        self.assertTrue(check_password("fresh-pass-777", self.user.password_hash))

        self.client.post(reverse("library:logout"))
        self.assertEqual(self.client.get(link).status_code, 400)  # пароль змінився — посилання згоріло

    def test_unknown_email_gets_same_answer_and_no_letter(self):
        response = self.client.post(reverse("library:password_reset"), {"email": "nobody@example.com"})
        self.assertContains(response, "Перевірте пошту")
        self.assertEqual(len(mail.outbox), 0)

    def test_reset_verifies_unconfirmed_email(self):
        user = self.make_user("bob", verified=False)
        link = reverse("library:password_reset_confirm", args=[make_reset_token(user)])
        self.client.post(link, {"password": "fresh-pass-777", "password_confirm": "fresh-pass-777"})
        user.refresh_from_db()
        self.assertIsNotNone(user.email_verified_at)

    def test_weak_new_password_rejected(self):
        link = reverse("library:password_reset_confirm", args=[make_reset_token(self.user)])
        response = self.client.post(link, {"password": "123", "password_confirm": "123"})
        self.assertEqual(response.context["error"], "Пароль має містити щонайменше 8 символів.")


class VerifyEmailCommandTests(GameVaultTestCase):
    def test_marks_user_verified(self):
        user = self.make_user("admin", verified=False)
        call_command("verify_email", "admin", stdout=StringIO())
        user.refresh_from_db()
        self.assertIsNotNone(user.email_verified_at)

    def test_token_for_verified_user_just_logs_in(self):
        user = self.make_user("alice")
        response = self.client.get(reverse("library:verify_email", args=[make_verify_token(user, user.email)]))
        self.assertRedirects(response, reverse("library:profile"))
