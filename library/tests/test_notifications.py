"""Сповіщення (дзвіночок) і автосинхронізація Steam."""

from datetime import timedelta
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from library.models import ExternalAccount, GameRequest, Notification, SocialConnection
from library.services import steam_autosync

from .base import GameVaultTestCase


class FriendNotificationTests(GameVaultTestCase):
    def setUp(self):
        self.alice = self.make_user("alice")
        self.bob = self.make_user("bob")

    def test_request_accept_flow(self):
        self.login(self.alice)
        self.client.post(reverse("library:add_friend", args=[self.bob.id]))
        note = Notification.objects.get(user=self.bob)
        self.assertEqual(note.kind, Notification.FRIEND_REQUEST)
        self.assertEqual(note.actor, self.alice)

        self.login(self.bob)
        home = self.client.get(reverse("library:home"))
        self.assertEqual(home.context["header_unread_count"], 1)
        self.assertContains(home, "хоче додати вас у друзі")

        connection = SocialConnection.objects.get()
        self.client.post(reverse("library:accept_connection", args=[connection.id]))
        self.assertFalse(Notification.objects.filter(user=self.bob, kind=Notification.FRIEND_REQUEST).exists())
        accepted = Notification.objects.get(user=self.alice)
        self.assertEqual(accepted.kind, Notification.FRIEND_ACCEPTED)
        self.assertEqual(accepted.actor, self.bob)

    def test_reject_and_cancel_remove_request_notification(self):
        connection = SocialConnection.objects.create(sender=self.alice, receiver=self.bob, status="pending", created_at=timezone.now())
        from library.services import notifications
        notifications.notify_friend_request(connection)

        self.login(self.alice)
        self.client.post(reverse("library:delete_connection", args=[connection.id]))  # відкликала заявку
        self.assertFalse(Notification.objects.filter(user=self.bob).exists())

    def test_friends_page_marks_friend_notifications_read(self):
        self.login(self.alice)
        self.client.post(reverse("library:add_friend", args=[self.bob.id]))
        self.login(self.bob)
        self.client.get(reverse("library:friends"))
        self.assertFalse(Notification.objects.filter(user=self.bob, read_at__isnull=True).exists())


class GameRequestNotificationTests(GameVaultTestCase):
    def setUp(self):
        self.admin = self.make_user("admin", admin=True)
        self.alice = self.make_user("alice")

    def make_request(self, title="Celeste"):
        return GameRequest.objects.create(user=self.alice, title=title, status="pending", created_at=timezone.now())

    def test_approved_and_rejected(self):
        approved, rejected = self.make_request("Celeste"), self.make_request("Bad Game")
        self.login(self.admin)
        self.client.post(reverse("library:approve_request", args=[approved.id]))
        self.client.post(reverse("library:reject_request", args=[rejected.id]))

        kinds = dict(Notification.objects.filter(user=self.alice).values_list("game_request__title", "kind"))
        self.assertEqual(kinds, {"Celeste": Notification.GAME_APPROVED, "Bad Game": Notification.GAME_REJECTED})
        game = Notification.objects.get(kind=Notification.GAME_APPROVED).game
        self.assertEqual(game.title, "Celeste")

        self.login(self.alice)
        self.client.get(reverse("library:game_detail", args=[game.id]))
        self.assertIsNotNone(Notification.objects.get(kind=Notification.GAME_APPROVED).read_at)
        self.assertIsNone(Notification.objects.get(kind=Notification.GAME_REJECTED).read_at)
        self.client.get(reverse("library:my_requests"))
        self.assertFalse(Notification.objects.filter(user=self.alice, read_at__isnull=True).exists())


class NotificationPageTests(GameVaultTestCase):
    def setUp(self):
        self.alice = self.make_user("alice")
        self.bob = self.make_user("bob")
        connection = SocialConnection.objects.create(sender=self.bob, receiver=self.alice, status="pending", created_at=timezone.now())
        from library.services import notifications
        notifications.notify_friend_request(connection)
        self.login(self.alice)

    def test_page_lists_and_marks_read(self):
        response = self.client.get(reverse("library:notifications"))
        self.assertContains(response, "bob")
        self.assertContains(response, "is-unread")
        self.assertFalse(Notification.objects.filter(read_at__isnull=True).exists())

    def test_mark_all_read_button(self):
        self.client.post(reverse("library:notifications_mark_read"), {"next": reverse("library:home")})
        self.assertFalse(Notification.objects.filter(read_at__isnull=True).exists())

    def test_only_own_notifications_visible(self):
        self.login(self.bob)
        self.assertNotContains(self.client.get(reverse("library:notifications")), "хоче додати вас у друзі")


SYNC_RESULT = {"synced_count": 1, "added_to_library_count": 0, "removed_count": 0,
               "details_fetched": 0, "details_pending": 0}


@override_settings(STEAM_AUTOSYNC=True, STEAM_AUTOSYNC_HOURS=6)
class SteamAutoSyncTests(GameVaultTestCase):
    def setUp(self):
        self.user = self.make_user("alice")
        self.account = self.make_steam_account(self.user)
        self.login(self.user)
        # Синхронно замість фонового потоку: тест і потік не бачили б спільної транзакції.
        start = mock.patch("library.services.steam_autosync._start", side_effect=steam_autosync._sync_and_unlock)
        start.start()
        self.addCleanup(start.stop)

    def visit(self):
        with mock.patch("library.services.steam_service.sync_steam_library", return_value=SYNC_RESULT) as sync:
            self.client.get(reverse("library:home"))
        return sync

    def set_last_sync(self, hours_ago):
        ExternalAccount.objects.filter(id=self.account.id).update(
            last_synced_at=None if hours_ago is None else timezone.now() - timedelta(hours=hours_ago)
        )

    def test_stale_account_syncs_on_visit(self):
        self.set_last_sync(7)
        self.assertEqual(self.visit().call_count, 1)

    def test_never_synced_account_syncs(self):
        self.set_last_sync(None)
        self.assertEqual(self.visit().call_count, 1)

    def test_fresh_account_is_not_synced(self):
        self.set_last_sync(1)
        self.assertEqual(self.visit().call_count, 0)

    def test_check_is_throttled_per_user(self):
        self.set_last_sync(7)
        self.visit()
        self.assertEqual(self.visit().call_count, 0)  # повторна перевірка не раніше ніж за 10 хв

    def test_running_sync_is_not_started_twice(self):
        self.set_last_sync(7)
        from django.core.cache import cache
        cache.add(f"steam-autosync:lock:{self.account.id}", 1)
        self.assertEqual(self.visit().call_count, 0)

    @override_settings(STEAM_AUTOSYNC=False)
    def test_can_be_disabled(self):
        self.set_last_sync(7)
        self.assertEqual(self.visit().call_count, 0)

    def test_sync_records_last_synced_at(self):
        from library.services.steam_service import sync_steam_library

        with mock.patch("library.services.steam_service.get_owned_games", return_value=[]), \
                mock.patch("library.services.steam_service.refresh_steam_apps",
                           return_value={"fetched": 0, "not_found": 0, "pending": 0, "error": None}):
            sync_steam_library(self.user, self.account)
        self.account.refresh_from_db()
        self.assertIsNotNone(self.account.last_synced_at)

    def test_command_syncs_only_stale(self):
        self.set_last_sync(7)
        fresh_user = self.make_user("bob")
        fresh = self.make_steam_account(fresh_user, steam_id="76561197960287931")
        ExternalAccount.objects.filter(id=fresh.id).update(last_synced_at=timezone.now())
        out = StringIO()
        with mock.patch("library.services.steam_service.sync_steam_library", return_value=SYNC_RESULT) as sync:
            call_command("sync_steam_all", "--delay", "0", stdout=out)
        self.assertEqual(sync.call_count, 1)
        self.assertEqual(sync.call_args.args[0], self.user)
        self.assertIn("Готово: 1 з 1.", out.getvalue())
