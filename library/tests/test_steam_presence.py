"""Хто зараз у грі (steam_presence): сесії, стрічка, сповіщення, видимість, досягнення Steam."""

from datetime import datetime, timedelta
from datetime import timezone as dt_timezone
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.template import Context, Template
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from library.models import (
    ActivityEvent,
    AppState,
    ExternalAccount,
    ExternalLibraryItem,
    Notification,
    PlaySession,
    SteamAchievement,
    SteamAchievementSchema,
    User,
    UserAchievement,
)
from library.services import activity, steam_achievements, steam_presence
from library.services.steam_service import SteamError

from .base import GameVaultTestCase

ALICE_STEAM = "76561197960000001"
BOB_STEAM = "76561197960000002"


def player(steam_id, appid=None, name=None):
    data = {"steamid": steam_id, "personaname": steam_id}
    if appid is not None:
        data["gameid"] = str(appid)
    if name is not None:
        data["gameextrainfo"] = name
    return data


class PresenceTestCase(GameVaultTestCase):
    def setUp(self):
        self.alice = self.make_user("alice")
        self.bob = self.make_user("bob")
        self.alice_account = self.make_steam_account(self.alice, ALICE_STEAM)
        self.bob_account = self.make_steam_account(self.bob, BOB_STEAM)
        # Полудень сьогодні: сесії тесту не перетинають північ (події за день зливаються).
        self.now = timezone.now().replace(hour=12, minute=0, second=0, microsecond=0)
        # Досягнення в цих тестах не цікавлять — Steam «нічого не знає».
        for name, value in (("_fetch_schema", []), ("_fetch_player_achievements", None)):
            patcher = mock.patch(f"library.services.steam_achievements.{name}", return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def poll(self, players, minutes=0):
        with mock.patch("library.services.steam_presence._fetch_summaries", return_value=players):
            return steam_presence.poll(now=self.now + timedelta(minutes=minutes))


class FetchPresenceTests(PresenceTestCase):
    def test_parses_steam_and_non_steam_games(self):
        players = [
            player(ALICE_STEAM, 1145360, "Hades"),
            player(BOB_STEAM, 12345678901234567890, "Мій емулятор"),
            player("76561197960000003"),
        ]
        with mock.patch("library.services.steam_presence._fetch_summaries", return_value=players):
            result = steam_presence.fetch_presence([ALICE_STEAM, BOB_STEAM, "76561197960000003"])

        self.assertEqual(result, {ALICE_STEAM: ("1145360", "Hades"), BOB_STEAM: (None, "Мій емулятор")})

    def test_batches_by_100(self):
        ids = [str(76561197960000000 + i) for i in range(250)]
        with mock.patch("library.services.steam_presence._fetch_summaries", return_value=[]) as fetch:
            steam_presence.fetch_presence(ids)
        self.assertEqual([len(call.args[0]) for call in fetch.call_args_list], [100, 100, 50])


class SessionTests(PresenceTestCase):
    def test_session_lifecycle_writes_feed_event(self):
        hades = self.make_game("Hades", steam_appid="1145360")

        summary = self.poll([player(ALICE_STEAM, 1145360, "Hades")])
        self.assertEqual(summary["started"], 1)
        session = PlaySession.objects.get()
        self.assertIsNone(session.ended_at)
        self.assertEqual(session.game, hades)

        self.poll([player(ALICE_STEAM, 1145360, "Hades")], minutes=1)
        # 44 хв без опитувань — довше за STALE_AFTER: стара сесія закривається, відкривається нова.
        self.poll([player(ALICE_STEAM, 1145360, "Hades")], minutes=45)
        self.assertEqual(PlaySession.objects.count(), 2)

        self.poll([player(ALICE_STEAM)], minutes=46)
        self.assertFalse(PlaySession.objects.filter(ended_at__isnull=True).exists())

        event = ActivityEvent.objects.get(event_type=ActivityEvent.PLAY_SESSION)
        self.assertEqual(event.game, hades)
        self.assertEqual(event.appid, "1145360")
        self.assertEqual(event.duration_minutes, 2)  # 1 хв першої сесії + 1 хв (мінімум) другої — злито за день

    def test_continuous_session_updates_last_seen(self):
        for minute in range(0, 31):
            self.poll([player(ALICE_STEAM, 620, "Portal 2")], minutes=minute)
        session = PlaySession.objects.get()
        self.assertEqual(session.minutes, 30)

        self.poll([], minutes=31)
        self.assertEqual(ActivityEvent.objects.get().duration_minutes, 30)

    def test_switching_games_closes_previous(self):
        self.poll([player(ALICE_STEAM, 620, "Portal 2")])
        self.poll([player(ALICE_STEAM, 400, "Portal")], minutes=1)

        closed = PlaySession.objects.get(appid="620")
        self.assertIsNotNone(closed.ended_at)
        self.assertTrue(PlaySession.objects.filter(appid="400", ended_at__isnull=True).exists())

    def test_non_steam_game_is_tracked_by_name(self):
        self.poll([player(ALICE_STEAM, 12345678901234567890, "Емулятор")])
        self.poll([], minutes=5)

        session = PlaySession.objects.get()
        self.assertIsNone(session.appid)
        event = ActivityEvent.objects.get()
        self.assertEqual(event.game_name, "Емулятор")
        self.assertIsNone(event.game)

    def test_steam_error_keeps_sessions_open(self):
        self.poll([player(ALICE_STEAM, 620, "Portal 2")])
        with mock.patch("library.services.steam_presence._fetch_summaries", side_effect=SteamError("offline")):
            summary = steam_presence.poll(now=self.now + timedelta(minutes=1))

        self.assertEqual(summary["error"], "offline")
        self.assertTrue(PlaySession.objects.filter(ended_at__isnull=True).exists())

    def test_unlinked_account_session_is_closed(self):
        self.poll([player(ALICE_STEAM, 620, "Portal 2")])
        ExternalAccount.objects.filter(id=self.alice_account.id).delete()
        self.poll([], minutes=1)
        self.assertFalse(PlaySession.objects.filter(ended_at__isnull=True).exists())

    def test_first_play_only_for_unplayed_game(self):
        self.make_steam_item(self.alice_account, 620, "Portal 2", playtime=0)
        self.make_steam_item(self.bob_account, 400, "Portal", playtime=300)

        self.poll([player(ALICE_STEAM, 620, "Portal 2"), player(BOB_STEAM, 400, "Portal")])
        self.assertTrue(PlaySession.objects.get(user=self.alice).first_play)
        self.assertFalse(PlaySession.objects.get(user=self.bob).first_play)

        self.poll([], minutes=1)
        self.assertEqual(ActivityEvent.objects.get(user=self.alice).status, "first")
        # Наступна сесія — вже не перший запуск.
        self.poll([player(ALICE_STEAM, 620, "Portal 2")], minutes=2)
        self.assertFalse(PlaySession.objects.get(user=self.alice, ended_at__isnull=True).first_play)


class FriendNotificationTests(PresenceTestCase):
    def setUp(self):
        super().setUp()
        self.game = self.make_game("Hades", steam_appid="1145360")
        self.make_friends(self.alice, self.bob)
        self.make_entry(self.bob, self.game)

    def test_friend_with_game_is_notified_once(self):
        self.poll([player(ALICE_STEAM, 1145360, "Hades")])
        note = Notification.objects.get(user=self.bob)
        self.assertEqual(note.kind, Notification.FRIEND_PLAYING)
        self.assertEqual(note.actor, self.alice)
        self.assertEqual(note.game, self.game)

        self.poll([], minutes=1)
        self.poll([player(ALICE_STEAM, 1145360, "Hades")], minutes=2)
        self.assertEqual(Notification.objects.filter(user=self.bob).count(), 1)  # кулдаун 12 год

        self.login(self.bob)
        self.assertContains(self.client.get(reverse("library:notifications")), "запускає")

    def test_respects_toggles(self):
        User.objects.filter(id=self.bob.id).update(notify_friend_playing=False)
        self.poll([player(ALICE_STEAM, 1145360, "Hades")])
        self.assertFalse(Notification.objects.exists())

        self.poll([], minutes=1)
        User.objects.filter(id=self.bob.id).update(notify_friend_playing=True)
        User.objects.filter(id=self.alice.id).update(show_playing_now=False)
        self.poll([player(ALICE_STEAM, 1145360, "Hades")], minutes=2)
        self.assertFalse(Notification.objects.exists())

    def test_no_notification_for_non_friends_or_other_games(self):
        stranger = self.make_user("carol")
        self.make_entry(stranger, self.game)
        self.poll([player(ALICE_STEAM, 620, "Portal 2")])
        self.assertFalse(Notification.objects.exists())


class LiveVisibilityTests(PresenceTestCase):
    def setUp(self):
        super().setUp()
        self.make_friends(self.alice, self.bob)

    def start(self, user, appid="620", name="Portal 2", seen=None):
        now = timezone.now()
        return PlaySession.objects.create(
            user=user, appid=appid, game_name=name, started_at=now - timedelta(minutes=20),
            last_seen_at=seen or now,
        )

    def test_friends_see_live_sessions(self):
        self.start(self.bob)
        self.assertEqual([s.user for s in steam_presence.live_sessions(self.alice)], [self.bob])

        carol = self.make_user("carol")
        self.assertEqual(steam_presence.live_sessions(carol), [])

    def test_hidden_and_stale_sessions_are_not_live(self):
        session = self.start(self.bob)
        User.objects.filter(id=self.bob.id).update(show_playing_now=False)
        self.assertEqual(steam_presence.live_sessions(self.alice), [])
        self.assertEqual(len(steam_presence.live_sessions(User.objects.get(id=self.bob.id))), 1)  # себе бачить

        User.objects.filter(id=self.bob.id).update(show_playing_now=True)
        PlaySession.objects.filter(id=session.id).update(last_seen_at=timezone.now() - timedelta(minutes=10))
        self.assertEqual(steam_presence.live_sessions(self.alice), [])

    def test_pages_show_live_status(self):
        game = self.make_game("Portal 2", steam_appid="620")
        self.make_entry(self.bob, game)
        session = self.start(self.bob)
        PlaySession.objects.filter(id=session.id).update(game=game)
        self.login(self.alice)

        self.assertContains(self.client.get(reverse("library:feed")), "У грі · 20 хв")
        self.assertContains(self.client.get(reverse("library:home")), "у грі 20 хв")
        self.assertContains(self.client.get(reverse("library:friends")), "gv-user-card__status")
        self.assertContains(self.client.get(reverse("library:user_profile", args=[self.bob.id])), "Грає в Portal 2")
        self.assertContains(self.client.get(reverse("library:game_detail", args=[game.id])), "Зараз у грі")

    def test_settings_toggles(self):
        self.login(self.alice)
        data = {"username": "alice", "email": "alice@example.com"}
        self.client.post(reverse("library:edit_profile"), data)
        alice = User.objects.get(id=self.alice.id)
        self.assertFalse(alice.show_playing_now)
        self.assertFalse(alice.notify_friend_playing)

        self.client.post(reverse("library:edit_profile"), {**data, "show_playing_now": "on", "notify_friend_playing": "on"})
        alice = User.objects.get(id=self.alice.id)
        self.assertTrue(alice.show_playing_now)
        self.assertTrue(alice.notify_friend_playing)


class PollSchedulingTests(PresenceTestCase):
    def test_claim_poll_once_per_interval(self):
        now = timezone.now()
        AppState.objects.filter(name=steam_presence.POLL_STATE).update(updated_at=now - timedelta(hours=1))
        self.assertTrue(steam_presence.claim_poll(now))
        self.assertFalse(steam_presence.claim_poll(now + timedelta(seconds=30)))
        self.assertTrue(steam_presence.claim_poll(now + timedelta(seconds=60)))

    @override_settings(STEAM_PRESENCE=True)
    def test_middleware_polls_in_background(self):
        AppState.objects.filter(name=steam_presence.POLL_STATE).update(updated_at=timezone.now() - timedelta(hours=1))
        self.login(self.alice)
        players = [player(ALICE_STEAM, 620, "Portal 2")]
        with mock.patch("library.services.steam_presence._start", side_effect=steam_presence._poll_and_unlock), \
                mock.patch("library.services.steam_presence._fetch_summaries", return_value=players):
            self.client.get(reverse("library:home"))
            self.client.get(reverse("library:home"))  # тік у кеші — вдруге не опитує
        self.assertEqual(PlaySession.objects.count(), 1)

    def test_command(self):
        out = StringIO()
        with mock.patch("library.services.steam_presence._fetch_summaries", return_value=[]):
            call_command("poll_steam_presence", "--force", stdout=out)
        self.assertIn("акаунтів: 2", out.getvalue())


class FeedEventTests(PresenceTestCase):
    def test_feed_renders_play_and_achievement_events(self):
        game = self.make_game("Hades", steam_appid="1145360")
        now = timezone.now()
        session = PlaySession.objects.create(
            user=self.alice, appid="1145360", game=game, game_name="Hades",
            started_at=now - timedelta(minutes=135), last_seen_at=now, ended_at=now,
        )
        activity.record_play_session(session)
        activity.record_achievements(session, 3)
        outside = PlaySession.objects.create(
            user=self.alice, appid="999", game_name="Поза каталогом",
            started_at=now - timedelta(minutes=5), last_seen_at=now, ended_at=now,
        )
        activity.record_play_session(outside)

        self.login(self.alice)
        response = self.client.get(reverse("library:feed") + "?filter=games")
        self.assertContains(response, "2 год 15 хв")
        self.assertContains(response, "отримує досягнення")
        self.assertContains(response, "store.steampowered.com/app/999/")
        self.assertEqual(len(response.context["items"]), 3)

    def test_minutes_label(self):
        template = Template("{% load library_extras %}{{ a|minutes_label }}|{{ b|minutes_label }}|{{ c|minutes_label }}")
        self.assertEqual(template.render(Context({"a": 45, "b": 120, "c": 135})), "45 хв|2 год|2 год 15 хв")


class AchievementTests(GameVaultTestCase):
    def setUp(self):
        self.alice = self.make_user("alice")
        self.account = self.make_steam_account(self.alice, ALICE_STEAM)
        self.item = self.make_steam_item(self.account, 1145360, "Hades", playtime=600)
        self.schema = [
            {"apiname": "WIN", "name": "Перемога", "description": "Втекти", "icon": "https://cdn/win.jpg",
             "icon_gray": None, "hidden": False, "percent": 4.5},
            {"apiname": "START", "name": "Початок", "description": None, "icon": "https://cdn/start.jpg",
             "icon_gray": None, "hidden": False, "percent": 80.0},
        ]

    def ts(self, dt):
        return int(dt.timestamp())

    def test_sync_user_game_stores_achievements_and_progress(self):
        old = datetime(2024, 1, 1, tzinfo=dt_timezone.utc)
        with mock.patch.object(steam_achievements, "_fetch_schema", return_value=self.schema) as schema, \
                mock.patch.object(steam_achievements, "_fetch_player_achievements", return_value=[("START", self.ts(old))]):
            self.assertEqual(steam_achievements.sync_user_game(self.alice.id, ALICE_STEAM, "1145360"), 1)
            self.assertEqual(steam_achievements.sync_user_game(self.alice.id, ALICE_STEAM, "1145360"), 0)
        schema.assert_called_once()  # схема — один раз на appid

        self.item.refresh_from_db()
        self.assertEqual((self.item.achievements_unlocked, self.item.achievements_total), (1, 2))
        self.assertEqual(SteamAchievement.objects.count(), 2)
        self.assertFalse(ActivityEvent.objects.exists())  # дозавантаження без подій у стрічці

    def test_session_check_records_only_new_achievements(self):
        now = timezone.now().replace(microsecond=0)
        session = PlaySession.objects.create(
            user=self.alice, appid="1145360", game_name="Hades",
            started_at=now - timedelta(hours=1), last_seen_at=now, ended_at=now,
        )
        unlocked = [("START", self.ts(now - timedelta(days=30))), ("WIN", self.ts(now - timedelta(minutes=10)))]
        with mock.patch.object(steam_achievements, "_fetch_schema", return_value=self.schema), \
                mock.patch.object(steam_achievements, "_fetch_player_achievements", return_value=unlocked):
            self.assertEqual(steam_achievements.process_pending_sessions(), 1)

        event = ActivityEvent.objects.get(event_type=ActivityEvent.ACHIEVEMENTS)
        self.assertEqual(event.item_count, 1)
        self.assertTrue(PlaySession.objects.get().achievements_checked)

        items = activity.build_feed(self.alice)
        self.assertEqual([a.name for a in items[0].achievements], ["Перемога"])
        self.assertTrue(items[0].achievements[0].is_rare)

    def test_game_without_achievements(self):
        with mock.patch.object(steam_achievements, "_fetch_schema", return_value=[]), \
                mock.patch.object(steam_achievements, "_fetch_player_achievements") as player_call:
            steam_achievements.backfill()
        player_call.assert_not_called()
        self.item.refresh_from_db()
        self.assertEqual(self.item.achievements_total, 0)
        self.assertIsNotNone(self.item.achievements_checked_at)
        self.assertTrue(SteamAchievementSchema.objects.filter(appid="1145360", total=0).exists())

    def test_backfill_picks_unchecked_played_games(self):
        self.make_steam_item(self.account, 400, "Portal", playtime=0)  # не грали — не перевіряємо
        items = steam_achievements.backfill_items(limit=10)
        self.assertEqual([i.external_game_id for i in items], ["1145360"])

    def test_pages_show_achievements(self):
        game = self.make_game("Hades", steam_appid="1145360")
        now = timezone.now()
        with mock.patch.object(steam_achievements, "_fetch_schema", return_value=self.schema), \
                mock.patch.object(steam_achievements, "_fetch_player_achievements",
                                  return_value=[("WIN", self.ts(now))]):
            steam_achievements.sync_user_game(self.alice.id, ALICE_STEAM, "1145360")

        self.login(self.alice)
        page = self.client.get(reverse("library:game_detail", args=[game.id]))
        self.assertEqual(page.context["achievements"]["percent"], 50)
        self.assertContains(page, "Ваші досягнення")
        self.assertContains(page, "Найрідкісніше")
        self.assertContains(page, "ваші досягнення")  # прогрес і в шапці гри

        profile = self.client.get(reverse("library:profile"))
        self.assertContains(profile, "Останні досягнення")
        self.assertContains(profile, "Перемога")
        self.assertContains(self.client.get(reverse("library:steam_library")), "1/2")

        self.client.post(reverse("library:steam_disconnect"))
        self.assertFalse(UserAchievement.objects.exists())  # дані Steam прибираються разом з акаунтом

    def test_fetch_command(self):
        out = StringIO()
        with mock.patch.object(steam_achievements, "_fetch_schema", return_value=self.schema), \
                mock.patch.object(steam_achievements, "_fetch_player_achievements", return_value=[]):
            call_command("fetch_steam_achievements", "--delay", "0", stdout=out)
        self.assertIn("Hades", out.getvalue())
        self.assertTrue(ExternalLibraryItem.objects.filter(achievements_checked_at__isnull=False).exists())
        self.assertFalse(UserAchievement.objects.exists())
