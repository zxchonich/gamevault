"""Волти: нарахування (ідемпотентність, ліміти, ретро за досягнення), магазин, подарунки, сторінки."""

from datetime import timedelta
from unittest import mock

from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from library.models import (
    ActivityEvent,
    Notification,
    PlaySession,
    SteamAchievement,
    User,
    UserAchievement,
    UserItem,
    UserSiteAchievement,
    VoltTransaction,
)
from library.services import shop, site_achievements, steam_achievements, steam_presence, volts

from .base import GameVaultTestCase


class VoltsTestCase(GameVaultTestCase):
    def setUp(self):
        self.alice = self.make_user("alice")

    def balance(self, user):
        return User.objects.get(id=user.id).volts

    def give(self, user, amount):
        User.objects.filter(id=user.id).update(volts=amount)
        user.volts = amount


class GrantTests(VoltsTestCase):
    def test_same_key_is_granted_once(self):
        self.assertEqual(volts.grant(self.alice.id, 10, volts.DAILY, "x"), 10)
        self.assertEqual(volts.grant(self.alice.id, 10, volts.DAILY, "x"), 0)
        self.assertEqual(self.balance(self.alice), 10)
        self.assertEqual(VoltTransaction.objects.filter(user=self.alice).count(), 1)

    def test_daily_cap_trims_and_stops(self):
        self.assertEqual(volts.grant(self.alice.id, 25, volts.SESSION, "s1", daily_cap=30), 25)
        self.assertEqual(volts.grant(self.alice.id, 25, volts.SESSION, "s2", daily_cap=30), 5)
        self.assertEqual(volts.grant(self.alice.id, 25, volts.SESSION, "s3", daily_cap=30), 0)
        self.assertEqual(self.balance(self.alice), 30)

    def test_session_reward_by_minutes(self):
        now = timezone.now()
        session = PlaySession.objects.create(
            user=self.alice, appid="620", game_name="Portal 2", started_at=now - timedelta(minutes=47),
            last_seen_at=now,
        )
        steam_presence.close_session(session)
        self.assertEqual(self.balance(self.alice), 4)

    def test_steam_achievements_only_from_session_and_rare_bonus(self):
        now = timezone.now()
        SteamAchievement.objects.create(appid="620", apiname="A", name="Звичайне", percent=50)
        SteamAchievement.objects.create(appid="620", apiname="B", name="Рідкісне", percent=3)
        account = self.make_steam_account(self.alice)
        session = PlaySession.objects.create(
            user=self.alice, appid="620", game_name="Portal 2", started_at=now - timedelta(minutes=30),
            last_seen_at=now, ended_at=now,
        )
        UserAchievement.objects.create(user=self.alice, appid="620", apiname="A", unlocked_at=now - timedelta(minutes=10))
        UserAchievement.objects.create(user=self.alice, appid="620", apiname="B", unlocked_at=now - timedelta(minutes=5))
        UserAchievement.objects.create(user=self.alice, appid="620", apiname="OLD", unlocked_at=now - timedelta(days=300))
        with mock.patch("library.services.steam_achievements.sync_user_game"):
            steam_achievements.check_session(session, account.external_user_id)
        self.assertEqual(self.balance(self.alice), volts.STEAM_ACH_REWARD + volts.STEAM_RARE_REWARD)

    def test_review_reward_needs_text_once_per_game_and_daily_limit(self):
        self.login(self.alice)
        long_text = "Дуже добра гра. " * 10
        games = [self.make_game(f"Гра {i}") for i in range(5)]
        self.client.post(reverse("library:add_review", args=[games[0].id]), {"score": 8, "text": "коротко"})
        self.assertEqual(self.balance(self.alice), 0)
        self.client.post(reverse("library:add_review", args=[games[0].id]), {"score": 8, "text": long_text})
        self.assertEqual(self.balance(self.alice), volts.REVIEW_REWARD)  # текст дописано — нараховано
        self.client.post(reverse("library:add_review", args=[games[0].id]), {"score": 9, "text": long_text + "!"})
        self.assertEqual(self.balance(self.alice), volts.REVIEW_REWARD)  # повторно — ні
        for game in games[1:]:
            self.client.post(reverse("library:add_review", args=[game.id]), {"score": 7, "text": long_text})
        self.assertEqual(self.balance(self.alice), volts.REVIEW_REWARD * volts.REVIEW_DAILY_LIMIT)

    def test_daily_visit_and_streak(self):
        start = timezone.now() - timedelta(days=6)
        for day in range(6):
            volts.daily_visit(self.alice.id, now=start + timedelta(days=day))
        self.assertEqual(self.balance(self.alice), 6 * volts.DAILY_REWARD)
        self.assertEqual(volts.daily_visit(self.alice.id, now=start + timedelta(days=6)),
                         volts.DAILY_REWARD + volts.STREAK_REWARD)
        self.assertEqual(volts.daily_visit(self.alice.id, now=start + timedelta(days=6)), 0)

    @override_settings(VOLTS_DAILY=True)
    def test_middleware_grants_daily_visit(self):
        from django.core.cache import cache

        cache.clear()
        self.login(self.alice)
        self.client.get(reverse("library:home"))
        self.client.get(reverse("library:home"))
        self.assertEqual(self.balance(self.alice), volts.DAILY_REWARD)

    def test_site_achievements_reward_including_retro(self):
        now = timezone.now()
        UserSiteAchievement.objects.create(user=self.alice, achievement_key="collector", tier=1, unlocked_at=now)
        UserSiteAchievement.objects.create(user=self.alice, achievement_key="collector", tier=2, unlocked_at=now)
        UserSiteAchievement.objects.create(user=self.alice, achievement_key="night_owl", tier=1, unlocked_at=now)
        site_achievements.check(self.alice)
        expected = volts.SITE_TIER_REWARD[1] + volts.SITE_TIER_REWARD[2] + volts.SITE_SINGLE_REWARD
        self.assertEqual(self.balance(self.alice), expected)
        site_achievements.check(self.alice)
        self.assertEqual(self.balance(self.alice), expected)


class ShopTests(VoltsTestCase):
    def test_buy_spends_once_and_equips(self):
        self.give(self.alice, 500)
        self.login(self.alice)
        self.client.post(reverse("library:buy_item", args=["frame_neon"]))
        alice = User.objects.get(id=self.alice.id)
        self.assertEqual(alice.volts, 300)
        self.assertEqual(alice.avatar_frame, "frame_neon")
        self.client.post(reverse("library:buy_item", args=["frame_neon"]))
        self.assertEqual(self.balance(self.alice), 300)
        self.assertEqual(VoltTransaction.objects.get(user=self.alice).amount, -200)

    def test_not_enough_volts(self):
        self.give(self.alice, 100)
        with self.assertRaises(shop.ShopError):
            shop.buy(self.alice, "frame_gold")
        self.assertEqual(self.balance(self.alice), 100)
        self.assertFalse(UserItem.objects.exists())

    def test_slots_in_order_extend_showcase(self):
        self.give(self.alice, 2000)
        with self.assertRaises(shop.ShopError):
            shop.buy(self.alice, "slot_7")
        shop.buy(self.alice, "slot_6")
        shop.buy(self.alice, "slot_7")
        self.assertEqual(shop.showcase_size(self.alice), 7)
        self.assertEqual(site_achievements.showcase_size(self.alice), 7)

    def test_paid_badge_style_requires_purchase(self):
        self.login(self.alice)
        self.client.post(reverse("library:save_showcase"), {"badge_style": "shield"})
        self.assertIsNone(User.objects.get(id=self.alice.id).badge_style)
        self.client.post(reverse("library:save_showcase"), {"badge_style": "hex"})
        self.assertEqual(User.objects.get(id=self.alice.id).badge_style, "hex")
        self.give(self.alice, 300)
        self.client.post(reverse("library:buy_item", args=["style_shield"]))
        self.assertEqual(User.objects.get(id=self.alice.id).badge_style, "shield")

    def test_equip_requires_ownership_and_unequip(self):
        self.login(self.alice)
        self.client.post(reverse("library:equip_item", args=["title_critic"]))
        self.assertIsNone(User.objects.get(id=self.alice.id).profile_title)
        UserItem.objects.create(user=self.alice, item_key="title_critic", acquired_at=timezone.now())
        self.client.post(reverse("library:equip_item", args=["title_critic"]))
        self.assertEqual(User.objects.get(id=self.alice.id).profile_title, "title_critic")
        profile = self.client.get(reverse("library:profile"))
        self.assertContains(profile, "gv-user-title")
        self.client.post(reverse("library:unequip_item", args=["title"]))
        self.assertIsNone(User.objects.get(id=self.alice.id).profile_title)


class GiftTests(VoltsTestCase):
    def setUp(self):
        super().setUp()
        self.bob = self.make_user("bob")
        self.make_friends(self.alice, self.bob)
        self.give(self.alice, 1000)

    def test_gift_with_feed_and_notification(self):
        self.login(self.alice)
        self.client.post(reverse("library:gift_item", args=["frame_neon"]), {"friend": self.bob.id, "show_in_feed": "1"})
        self.assertEqual(self.balance(self.alice), 800)
        item = UserItem.objects.get(user=self.bob, item_key="frame_neon")
        self.assertEqual(item.gifted_by_id, self.alice.id)
        self.assertTrue(Notification.objects.filter(user=self.bob, kind=Notification.GIFT, item_key="frame_neon").exists())
        self.assertTrue(ActivityEvent.objects.filter(user=self.alice, event_type=ActivityEvent.GIFT).exists())

        feed = self.client.get(reverse("library:feed"))
        self.assertContains(feed, "дарує")
        self.assertContains(feed, "рамку аватара «Неон»")

        self.login(self.bob)
        bell = self.client.get(reverse("library:notifications"))
        self.assertContains(bell, "дарує вам")

    def test_gift_hidden_from_feed(self):
        shop.gift(self.alice, self.bob, "title_hunter", show_in_feed=False)
        self.assertFalse(ActivityEvent.objects.filter(event_type=ActivityEvent.GIFT).exists())
        self.assertTrue(Notification.objects.filter(user=self.bob, kind=Notification.GIFT).exists())

    def test_gift_rules(self):
        carol = self.make_user("carol")
        with self.assertRaises(shop.ShopError):
            shop.gift(self.alice, carol, "frame_neon")             # не друг
        with self.assertRaises(shop.ShopError):
            shop.gift(self.alice, self.bob, "slot_6")              # не дарується
        UserItem.objects.create(user=self.bob, item_key="frame_pixel", acquired_at=timezone.now())
        with self.assertRaises(shop.ShopError):
            shop.gift(self.alice, self.bob, "frame_pixel")         # уже є
        self.assertEqual(self.balance(self.alice), 1000)


class PageTests(VoltsTestCase):
    def test_pages_render(self):
        self.give(self.alice, 250)
        volts.grant(self.alice.id, 5, volts.DAILY, "daily:test", note="")
        bob = self.make_user("bob")
        self.make_friends(self.alice, bob)
        self.login(self.alice)
        response = self.client.get(reverse("library:shop"))
        self.assertContains(response, "Магазин")
        self.assertContains(response, "frame_neon")
        self.assertContains(response, 'name="show_in_feed"')
        wallet = self.client.get(reverse("library:wallet"))
        self.assertContains(wallet, "Щоденний візит")
        self.assertContains(wallet, "Як заробити")
        home = self.client.get(reverse("library:home"))
        self.assertContains(home, "gv-volts")
