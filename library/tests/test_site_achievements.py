"""Досягнення GameVault: метрики, рівні, тиха перша видача, сповіщення, сторінки, вітрина."""

from datetime import datetime, timedelta
from io import StringIO

from django.core.management import call_command
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from library.models import (
    ActivityEvent,
    GameGenre,
    GameRequest,
    Genre,
    Notification,
    PlaySession,
    Review,
    SteamAchievement,
    User,
    UserAchievement,
    UserSiteAchievement,
)
from library.services import activity, badge_styles, site_achievements
from library.services.site_achievements import BY_KEY, _longest_streak, _played_at_night, compute_metrics

from .base import GameVaultTestCase


def tiers(user):
    return site_achievements.unlocked_tiers(user)


class SiteAchievementTestCase(GameVaultTestCase):
    def setUp(self):
        self.alice = self.make_user("alice")

    def synced(self, user):
        """Користувач, якому досягнення вже рахували (наступні видачі — зі сповіщеннями)."""
        User.objects.filter(id=user.id).update(achievements_synced_at=timezone.now())
        return User.objects.get(id=user.id)

    def add_games(self, user, count, status="planned", genre=None):
        games = []
        for index in range(count):
            game = self.make_game(f"{user.username} {status} {index} {genre.name if genre else ''}")
            if genre is not None:
                GameGenre.objects.create(game=game, genre=genre)
            self.make_entry(user, game, status)
            games.append(game)
        return games


class TierTests(SiteAchievementTestCase):
    def test_tier_for(self):
        collector = BY_KEY["collector"]
        self.assertEqual([collector.tier_for(v) for v in (0, 9, 10, 49, 50, 100, 500)], [0, 0, 1, 1, 2, 3, 3])
        self.assertEqual(BY_KEY["connected"].tier_for(1), 1)

    def test_library_metrics(self):
        genres = [Genre.objects.create(name=f"G{i}") for i in range(3)]
        for genre in genres:
            self.add_games(self.alice, 1, "completed", genre)
        self.add_games(self.alice, 17)
        m = compute_metrics(self.alice)
        self.assertEqual((m["collector"], m["finisher"], m["omnivore"], m["no_dropped"]), (20, 3, 3, 20))

        self.add_games(self.alice, 1, "dropped")
        self.assertEqual(compute_metrics(self.alice, ["no_dropped"])["no_dropped"], 0)

    def test_review_and_social_metrics(self):
        bob = self.make_user("bob")
        self.make_friends(self.alice, bob)
        for score, text in ((2, "погано"), (10, "x" * 600)):
            Review.objects.create(user=self.alice, game=self.make_game(f"R{score}"), score=score, text=text,
                                  created_at=timezone.now())
        GameRequest.objects.create(user=self.alice, title="Нова", status="approved", created_at=timezone.now())
        m = compute_metrics(self.alice)
        self.assertEqual((m["critic"], m["writer"], m["fair_judge"], m["soul"], m["pioneer"]), (2, 600, 2, 1, 1))

    def test_steam_metrics(self):
        account = self.make_steam_account(self.alice)
        item = self.make_steam_item(account, 620, "Portal 2", playtime=6000)
        item.achievements_total = item.achievements_unlocked = 10
        item.save()
        SteamAchievement.objects.create(appid="620", apiname="RARE", name="Рідкісне", percent=2)
        SteamAchievement.objects.create(appid="620", apiname="COMMON", name="Звичайне", percent=60)
        for name in ("RARE", "COMMON"):
            UserAchievement.objects.create(user=self.alice, appid="620", apiname=name, unlocked_at=timezone.now())

        m = compute_metrics(self.alice)
        self.assertEqual((m["connected"], m["veteran"], m["hunter"], m["rare_find"], m["perfectionist"]),
                         (1, 100, 2, 1, 1))

    def test_session_helpers(self):
        tz = timezone.get_current_timezone()
        day = datetime(2026, 3, 10, tzinfo=tz)
        evening = (day.replace(hour=20), day.replace(hour=23))
        across_three = (day.replace(hour=23), day.replace(hour=23) + timedelta(hours=5))
        self.assertFalse(_played_at_night([evening]))
        self.assertTrue(_played_at_night([across_three]))
        self.assertTrue(_played_at_night([(day.replace(hour=3, minute=20), day.replace(hour=3, minute=40))]))

        sessions = [(day + timedelta(days=d, hours=18), day + timedelta(days=d, hours=19)) for d in (0, 1, 2, 5)]
        self.assertEqual(_longest_streak(sessions), 3)

    def test_marathon_from_sessions(self):
        now = timezone.now()
        PlaySession.objects.create(user=self.alice, game_name="X", started_at=now - timedelta(hours=7),
                                   last_seen_at=now, ended_at=now)
        self.assertEqual(compute_metrics(self.alice, ["marathon"])["marathon"], 7.0)


class AwardTests(SiteAchievementTestCase):
    def test_first_check_is_silent(self):
        self.add_games(self.alice, 12, "completed")
        new = site_achievements.check(self.alice)

        self.assertIn(("collector", 1), [(a.key, t) for a, t in new])
        self.assertEqual(tiers(self.alice)["finisher"], 2)
        self.assertFalse(ActivityEvent.objects.filter(event_type=ActivityEvent.SITE_ACHIEVEMENT).exists())
        self.assertFalse(Notification.objects.exists())
        self.assertIsNotNone(User.objects.get(id=self.alice.id).achievements_synced_at)

    def test_later_unlocks_notify_once_with_top_tier(self):
        alice = self.synced(self.alice)
        self.add_games(alice, 10, "completed")
        site_achievements.check(alice)

        events = ActivityEvent.objects.filter(event_type=ActivityEvent.SITE_ACHIEVEMENT)
        self.assertEqual(
            sorted(events.values_list("achievement_key", "item_count")), [("collector", 1), ("finisher", 2)]
        )
        self.assertEqual(Notification.objects.filter(kind=Notification.SITE_ACHIEVEMENT).count(), 2)
        self.assertEqual(UserSiteAchievement.objects.filter(user=alice, achievement_key="finisher").count(), 2)

        self.assertEqual(site_achievements.check(alice), [])  # повторно нічого не видає
        self.assertEqual(events.count(), 2)

    @override_settings(SITE_ACHIEVEMENTS=True)
    def test_actions_trigger_check(self):
        alice = self.synced(self.alice)
        game = self.make_game("Hades")
        self.make_entry(alice, game, "completed")
        activity.record_status_change(alice, game, "completed")

        note = Notification.objects.get(kind=Notification.SITE_ACHIEVEMENT)
        self.assertEqual((note.achievement_key, note.tier), ("finisher", 1))

        self.login(alice)
        self.assertContains(self.client.get(reverse("library:notifications")), "Нове досягнення")
        feed = self.client.get(reverse("library:feed") + "?filter=achievements")
        self.assertContains(feed, "«Фінішер»")

    @override_settings(SITE_ACHIEVEMENTS=True)
    def test_friendship_checks_both_users(self):
        bob = self.synced(self.make_user("bob"))
        alice = self.synced(self.alice)
        self.make_friends(alice, bob)
        activity.record_friendship(alice, bob)
        self.assertEqual(tiers(alice)["soul"], 1)
        self.assertEqual(tiers(bob)["soul"], 1)

    def test_command(self):
        self.add_games(self.alice, 10)
        out = StringIO()
        call_command("award_site_achievements", stdout=out)
        self.assertIn("alice (тихо)", out.getvalue())
        self.assertEqual(tiers(self.alice)["collector"], 1)


class PageTests(SiteAchievementTestCase):
    def setUp(self):
        super().setUp()
        self.add_games(self.alice, 10, "completed")
        site_achievements.check(self.alice)
        self.alice = User.objects.get(id=self.alice.id)

    def test_own_page(self):
        self.login(self.alice)
        response = self.client.get(reverse("library:my_achievements"))
        self.assertContains(response, "Колекціонер")
        self.assertContains(response, "до срібла")
        self.assertContains(response, "???")  # секретні
        self.assertNotContains(response, "Нічна сова")
        self.assertContains(response, "є в 100% гравців")  # alice — єдиний користувач

    def test_other_user_page_respects_privacy(self):
        bob = self.make_user("bob")
        self.login(bob)
        self.assertContains(self.client.get(reverse("library:user_achievements", args=[self.alice.id])), "Фінішер")

        User.objects.filter(id=self.alice.id).update(is_private=True)
        response = self.client.get(reverse("library:user_achievements", args=[self.alice.id]))
        self.assertTemplateUsed(response, "library/private_profile.html")

    def test_profile_showcase_and_saving(self):
        self.login(self.alice)
        profile = self.client.get(reverse("library:profile"))
        self.assertEqual([v.key for v in profile.context["site_showcase"]], ["finisher", "collector"])
        self.assertContains(profile, "data-showcase-form")

        self.client.post(reverse("library:save_showcase"), {"keys": ["collector", "night_owl", "collector", "bogus"]})
        self.assertEqual(User.objects.get(id=self.alice.id).achievement_showcase, "collector")
        profile = self.client.get(reverse("library:profile"))
        self.assertEqual([v.key for v in profile.context["site_showcase"]], ["collector"])

        self.client.post(reverse("library:save_showcase"), {"auto": "1"})
        self.assertIsNone(User.objects.get(id=self.alice.id).achievement_showcase)

    def test_badge_style_saving_and_owner_style_for_viewers(self):
        self.login(self.alice)
        profile = self.client.get(reverse("library:profile"))
        self.assertEqual(profile.context["badge_style"], badge_styles.DEFAULT_STYLE)
        self.assertContains(profile, 'gv-badge--emblem')
        self.assertContains(profile, 'name="badge_style" value="shield"')

        self.client.post(reverse("library:save_showcase"), {"keys": ["collector"], "badge_style": "shield"})
        self.assertEqual(User.objects.get(id=self.alice.id).badge_style, "shield")

        # Чужий профіль і сторінка досягнень — у стилі власника, без вибору стилю.
        bob = self.make_user("bob")
        self.login(bob)
        response = self.client.get(reverse("library:user_profile", args=[self.alice.id]))
        self.assertContains(response, "gv-badge--shield")
        self.assertNotContains(response, 'name="badge_style"')
        page = self.client.get(reverse("library:user_achievements", args=[self.alice.id]))
        self.assertContains(page, "gv-badge--shield")

    def test_badge_style_invalid_or_default_is_stored_as_null(self):
        self.login(self.alice)
        self.client.post(reverse("library:save_showcase"), {"badge_style": "hex"})
        self.assertEqual(User.objects.get(id=self.alice.id).badge_style, "hex")
        self.client.post(reverse("library:save_showcase"), {"badge_style": "<script>"})
        self.assertIsNone(User.objects.get(id=self.alice.id).badge_style)
        self.client.post(reverse("library:save_showcase"), {"badge_style": "hex"})
        self.client.post(reverse("library:save_showcase"), {"badge_style": badge_styles.DEFAULT_STYLE})
        self.assertIsNone(User.objects.get(id=self.alice.id).badge_style)

    def test_every_style_renders_every_achievement(self):
        for style in badge_styles.STYLES:
            for achievement in site_achievements.ACHIEVEMENTS:
                self.assertIn(achievement.icon, badge_styles.ICONS)
                for tier in (0, 1, 3):
                    for compact in (False, True):
                        svg = badge_styles.render(style, achievement.icon, tier=tier, single=achievement.single,
                                                  locked=tier == 0, hidden=tier == 0 and achievement.secret,
                                                  compact=compact)
                        self.assertTrue(svg.startswith("<svg viewBox="), (style, achievement.key))

    def test_other_profile_shows_showcase_without_editor(self):
        bob = self.make_user("bob")
        self.login(bob)
        response = self.client.get(reverse("library:user_profile", args=[self.alice.id]))
        self.assertContains(response, "Досягнення GameVault")
        self.assertNotContains(response, "data-showcase-form")
