"""Повторні заявки в друзі після відхилення та чорний список."""

from django.urls import reverse

from library.models import ActivityEvent, Notification, SocialConnection, UserBlock
from library.services import activity

from .base import GameVaultTestCase


class FriendRequestTests(GameVaultTestCase):
    def setUp(self):
        self.alice = self.make_user("alice")
        self.bob = self.make_user("bob")

    def add(self, user, target):
        self.login(user)
        return self.client.post(reverse("library:add_friend", args=[target.id]))

    def test_request_can_be_resent_after_rejection(self):
        for _ in range(3):
            self.add(self.alice, self.bob)
            connection = SocialConnection.objects.get()
            self.assertEqual((connection.sender, connection.status), (self.alice, "pending"))
            self.assertTrue(Notification.objects.filter(user=self.bob, kind=Notification.FRIEND_REQUEST).exists())

            self.login(self.bob)
            self.client.post(reverse("library:reject_connection", args=[connection.id]))
            self.assertEqual(SocialConnection.objects.get().status, "rejected")

        # Той, хто відхилив, теж може надіслати заявку.
        self.add(self.bob, self.alice)
        connection = SocialConnection.objects.get()
        self.assertEqual((connection.sender, connection.status), (self.bob, "pending"))

    def test_counter_request_is_accepted(self):
        self.add(self.alice, self.bob)
        self.add(self.bob, self.alice)
        self.assertEqual(SocialConnection.objects.get().status, "accepted")
        self.assertTrue(Notification.objects.filter(user=self.alice, kind=Notification.FRIEND_ACCEPTED).exists())


class BlockTests(GameVaultTestCase):
    def setUp(self):
        self.alice = self.make_user("alice")
        self.bob = self.make_user("bob")
        self.carol = self.make_user("carol")

    def block(self, user, target):
        self.login(user)
        return self.client.post(reverse("library:block_user", args=[target.id]))

    def test_block_removes_friendship_and_notifications(self):
        connection = self.make_friends(self.alice, self.bob)
        Notification.objects.create(user=self.alice, kind=Notification.FRIEND_ACCEPTED, actor=self.bob,
                                    connection=connection, created_at=connection.created_at)

        self.block(self.alice, self.bob)
        self.assertTrue(UserBlock.objects.filter(blocker=self.alice, blocked=self.bob).exists())
        self.assertFalse(SocialConnection.objects.exists())
        self.assertFalse(Notification.objects.exists())

    def test_blocked_user_cannot_send_requests_or_see_profile(self):
        self.block(self.alice, self.bob)

        self.login(self.bob)
        self.client.post(reverse("library:add_friend", args=[self.alice.id]))
        self.assertFalse(SocialConnection.objects.exists())

        profile = self.client.get(reverse("library:user_profile", args=[self.alice.id]))
        self.assertTemplateUsed(profile, "library/private_profile.html")
        self.assertContains(profile, "Заявки недоступні")
        self.assertNotContains(profile, "заблок")  # про блокування не повідомляємо
        library = self.client.get(reverse("library:user_library", args=[self.alice.id]))
        self.assertTemplateUsed(library, "library/private_profile.html")
        self.assertRedirects(self.client.get(reverse("library:user_steam_library", args=[self.alice.id])),
                             reverse("library:user_profile", args=[self.alice.id]), fetch_redirect_response=False)

        users = self.client.get(reverse("library:user_list"))
        self.assertNotIn(self.alice.id, [item["user"].id for item in users.context["users_data"]])

    def test_blocker_must_unblock_before_adding(self):
        self.block(self.alice, self.bob)
        self.client.post(reverse("library:add_friend", args=[self.bob.id]))
        self.assertFalse(SocialConnection.objects.exists())

        profile = self.client.get(reverse("library:user_profile", args=[self.bob.id]))
        self.assertContains(profile, "Розблокувати")
        self.assertContains(self.client.get(reverse("library:edit_profile")), "bob")

        self.client.post(reverse("library:unblock_user", args=[self.bob.id]))
        self.assertFalse(UserBlock.objects.exists())
        self.client.post(reverse("library:add_friend", args=[self.bob.id]))
        self.assertTrue(SocialConnection.objects.filter(sender=self.alice, receiver=self.bob).exists())

    def test_block_from_incoming_request(self):
        self.login(self.bob)
        self.client.post(reverse("library:add_friend", args=[self.alice.id]))
        self.login(self.alice)
        self.assertContains(self.client.get(reverse("library:friends")), "Заблокувати")

        self.client.post(reverse("library:block_user", args=[self.bob.id]), {"next": reverse("library:friends")})
        self.assertFalse(SocialConnection.objects.exists())
        self.assertFalse(Notification.objects.filter(user=self.alice).exists())

    def test_feed_hides_blocked_users_both_ways(self):
        self.make_friends(self.carol, self.alice)
        self.make_friends(self.carol, self.bob)
        activity.record_friendship(self.carol, self.alice)  # «carol і alice тепер друзі»
        activity.record_library_add(self.carol, self.make_game("Hades"))

        self.block(self.alice, self.bob)
        self.login(self.bob)
        feed = activity.build_feed(self.bob)
        self.assertEqual([item.event_type for item in feed], [ActivityEvent.LIBRARY_ADD])

    def test_cannot_block_self(self):
        self.block(self.alice, self.alice)
        self.assertFalse(UserBlock.objects.exists())
