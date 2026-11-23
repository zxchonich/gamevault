from datetime import timedelta
from unittest import mock

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from library.models import ActivityEvent, GameRequest, Review, User
from library.services import activity

from .base import GameVaultTestCase


def events_of(user, event_type=None):
    queryset = ActivityEvent.objects.filter(user=user)
    if event_type:
        queryset = queryset.filter(event_type=event_type)
    return queryset


class RecordingTests(GameVaultTestCase):
    def setUp(self):
        self.user = self.make_user("alice")
        self.game = self.make_game("Hades")
        self.login(self.user)

    def test_add_to_library_records_once(self):
        url = reverse("library:add_to_library", args=[self.game.id])
        self.client.post(url)
        self.client.post(url)

        self.assertEqual(events_of(self.user, ActivityEvent.LIBRARY_ADD).count(), 1)

    def test_status_changes_are_recorded_and_merged(self):
        entry = self.make_entry(self.user, self.game, status="planned")
        url = reverse("library:update_library_status", args=[entry.id])

        self.client.post(url, {"status": "planned"})
        self.assertFalse(events_of(self.user, ActivityEvent.STATUS_CHANGE).exists())

        self.client.post(url, {"status": "playing"})
        self.client.post(url, {"status": "completed"})
        events = events_of(self.user, ActivityEvent.STATUS_CHANGE)
        self.assertEqual(list(events.values_list("status", flat=True)), ["completed"])

    def test_status_change_after_merge_window_is_new_event(self):
        entry = self.make_entry(self.user, self.game, status="planned")
        url = reverse("library:update_library_status", args=[entry.id])
        self.client.post(url, {"status": "playing"})
        events_of(self.user).update(created_at=timezone.now() - timedelta(hours=1))

        self.client.post(url, {"status": "completed"})

        self.assertEqual(events_of(self.user, ActivityEvent.STATUS_CHANGE).count(), 2)

    def test_review_recorded_and_unchanged_score_ignored(self):
        url = reverse("library:add_review", args=[self.game.id])
        self.client.post(url, {"score": "7", "text": "ok"})
        self.client.post(url, {"score": "7", "text": "edited text"})
        self.client.post(url, {"score": "9", "text": "better"})

        events = events_of(self.user, ActivityEvent.REVIEW)
        self.assertEqual(list(events.values_list("score", flat=True)), [9])

    def test_removing_game_forgets_its_events(self):
        entry = self.make_entry(self.user, self.game)
        activity.record_library_add(self.user, self.game)
        activity.record_status_change(self.user, self.game, "completed")
        activity.record_review(self.user, self.game, 8)
        Review.objects.create(user=self.user, game=self.game, score=8, created_at=timezone.now())

        self.client.post(reverse("library:delete_library_entry", args=[entry.id]))

        self.assertFalse(events_of(self.user).exists())

    def test_deleting_review_forgets_review_event(self):
        review = Review.objects.create(user=self.user, game=self.game, score=8, created_at=timezone.now())
        activity.record_review(self.user, self.game, 8)
        activity.record_library_add(self.user, self.game)

        self.client.post(reverse("library:admin_review_delete", args=[review.id]))

        self.assertEqual(list(events_of(self.user).values_list("event_type", flat=True)), [ActivityEvent.LIBRARY_ADD])

    def test_friendship_recorded_once(self):
        bob = self.make_user("bob")
        connection_ = self.make_friends(bob, self.user, status="pending")
        url = reverse("library:accept_connection", args=[connection_.id])

        self.client.post(url)
        self.client.post(url)

        event = ActivityEvent.objects.get(event_type=ActivityEvent.FRIENDSHIP)
        self.assertEqual((event.user, event.target_user), (self.user, bob))

    def test_approved_request_recorded_for_requester(self):
        admin = self.make_user("root", admin=True)
        request = GameRequest.objects.create(user=self.user, title="Celeste", status="pending",
                                             created_at=timezone.now())
        self.login(admin)

        self.client.post(reverse("library:approve_request", args=[request.id]))

        event = ActivityEvent.objects.get(event_type=ActivityEvent.GAME_APPROVED)
        self.assertEqual((event.user, event.game.title), (self.user, "Celeste"))

    def test_steam_sync_records_single_import_event(self):
        self.make_steam_account(self.user)
        result = {"synced_count": 30, "added_to_library_count": 12, "removed_count": 0,
                  "details_fetched": 0, "details_pending": 0}
        with mock.patch("library.views.steam.sync_steam_library", return_value=result):
            self.client.post(reverse("library:steam_sync_library"))
        result["added_to_library_count"] = 0
        with mock.patch("library.views.steam.sync_steam_library", return_value=result):
            self.client.post(reverse("library:steam_sync_library"))

        events = events_of(self.user, ActivityEvent.STEAM_IMPORT)
        self.assertEqual(list(events.values_list("item_count", flat=True)), [12])


class FeedVisibilityTests(GameVaultTestCase):
    def setUp(self):
        self.alice = self.make_user("alice")
        self.bob = self.make_user("bob")
        self.stranger = self.make_user("stranger")
        self.make_friends(self.alice, self.bob)
        self.game = self.make_game("Hades")

    def feed_authors(self, viewer):
        return [item.user.username for item in activity.build_feed(viewer)]

    def test_feed_shows_own_and_friends_events_only(self):
        for user in (self.alice, self.bob, self.stranger):
            activity.record_library_add(user, self.game)

        self.assertEqual(sorted(self.feed_authors(self.alice)), ["alice", "bob"])

    def test_hidden_activity_is_not_shown_to_others(self):
        activity.record_library_add(self.bob, self.game)
        User.objects.filter(id=self.bob.id).update(show_activity=False)

        self.assertEqual(self.feed_authors(self.alice), [])
        self.assertEqual(self.feed_authors(User.objects.get(id=self.bob.id)), ["bob"])  # свої видно завжди

    def test_friend_befriending_stranger_is_shown_unless_target_hidden(self):
        activity.record_friendship(self.bob, self.stranger)
        self.assertEqual(self.feed_authors(self.alice), ["bob"])

        User.objects.filter(id=self.stranger.id).update(show_activity=False)
        self.assertEqual(self.feed_authors(self.alice), [])

    def test_now_playing_respects_friends_and_visibility(self):
        for user, appid in ((self.bob, 1), (self.stranger, 2), (self.alice, 3)):
            account = self.make_steam_account(user, steam_id=f"7656119796028793{appid}")
            self.make_steam_item(account, appid, f"Game {appid}", playtime=600, playtime_2weeks=120)

        self.assertEqual({i.user.username for i in activity.now_playing(self.alice)}, {"alice", "bob"})

        User.objects.filter(id=self.bob.id).update(show_activity=False)
        self.assertEqual({i.user.username for i in activity.now_playing(self.alice)}, {"alice"})

    def test_profile_activity_respects_privacy_and_setting(self):
        activity.record_library_add(self.stranger, self.game)
        self.login(self.alice)
        url = reverse("library:user_profile", args=[self.stranger.id])

        self.assertEqual(len(self.client.get(url).context["recent_activity"]), 1)

        User.objects.filter(id=self.stranger.id).update(show_activity=False)
        self.assertEqual(self.client.get(url).context["recent_activity"], [])

        User.objects.filter(id=self.stranger.id).update(show_activity=True, is_private=True)
        self.assertTemplateUsed(self.client.get(url), "library/private_profile.html")


class FeedGroupingAndPagesTests(GameVaultTestCase):
    def setUp(self):
        self.alice = self.make_user("alice")
        self.login(self.alice)

    def test_same_day_adds_are_grouped(self):
        games = [self.make_game(f"Game {i}") for i in range(5)]
        for game in games:
            activity.record_library_add(self.alice, game)
        activity.record_status_change(self.alice, games[0], "completed")

        items = activity.build_feed(self.alice)

        self.assertEqual([i.event_type for i in items], [ActivityEvent.STATUS_CHANGE, ActivityEvent.LIBRARY_ADD])
        self.assertEqual((len(items[1].games), items[1].extra_games_count), (5, 2))

    def test_different_days_are_not_grouped(self):
        old = activity.record_library_add(self.alice, self.make_game("Old"))
        ActivityEvent.objects.filter(id=old.id).update(created_at=timezone.now() - timedelta(days=2))
        activity.record_library_add(self.alice, self.make_game("New"))

        self.assertEqual(len(activity.build_feed(self.alice)), 2)

    def test_feed_page_and_pagination(self):
        game = self.make_game("Hades")
        now = timezone.now()
        ActivityEvent.objects.bulk_create([
            ActivityEvent(user=self.alice, event_type=ActivityEvent.REVIEW, game=game, score=8,
                          created_at=now - timedelta(minutes=i))
            for i in range(activity.FEED_PAGE_SIZE + 5)
        ])

        first = self.client.get(reverse("library:feed"))
        self.assertTrue(first.context["has_more"])
        self.assertEqual(len(first.context["items"]), activity.FEED_PAGE_SIZE)
        self.assertContains(first, "оцінює")

        second = self.client.get(reverse("library:feed") + "?page=2")
        self.assertFalse(second.context["has_more"])
        self.assertEqual(len(second.context["items"]), 5)

    def test_feed_query_count_is_constant(self):
        bob = self.make_user("bob")
        self.make_friends(self.alice, bob)

        def count():
            with CaptureQueriesContext(connection) as ctx:
                activity.build_feed(self.alice, limit=50)
            return len(ctx.captured_queries)

        first = self.make_game("First")
        activity.record_library_add(bob, first)
        activity.record_review(bob, first, 9)  # уривки рецензій — один запит, коли є оцінки
        small = count()
        for i in range(10):
            game = self.make_game(f"Game {i}")
            activity.record_library_add(bob, game)
            activity.record_review(bob, game, 8)

        self.assertEqual(count(), small)

    def test_home_and_profile_show_activity(self):
        activity.record_library_add(self.alice, self.make_game("Hades"))

        self.assertContains(self.client.get(reverse("library:home")), "Уся стрічка")
        self.assertEqual(len(self.client.get(reverse("library:profile")).context["recent_activity"]), 1)

    def test_edit_profile_toggles_show_activity(self):
        data = {"username": "alice", "email": "alice@example.com"}

        self.client.post(reverse("library:edit_profile"), data)
        self.assertFalse(User.objects.get(id=self.alice.id).show_activity)

        self.client.post(reverse("library:edit_profile"), {**data, "show_activity": "on"})
        self.assertTrue(User.objects.get(id=self.alice.id).show_activity)


class FeedFiltersAndDetailsTests(GameVaultTestCase):
    def setUp(self):
        self.alice = self.make_user("alice")
        self.bob = self.make_user("bob")
        self.make_friends(self.alice, self.bob)
        self.game = self.make_game("Hades")
        activity.record_library_add(self.alice, self.game)
        activity.record_review(self.bob, self.game, 9)
        activity.record_status_change(self.bob, self.make_game("Celeste"), "completed")
        Review.objects.create(user=self.bob, game=self.game, score=9, text="Чудова гра", created_at=timezone.now())
        self.login(self.alice)

    def types(self, kind):
        return sorted(e.event_type for e in activity.feed_events(self.alice, kind))

    def test_filters(self):
        self.assertEqual(self.types("mine"), ["library_add"])
        self.assertEqual(self.types("friends"), ["review", "status_change"])
        self.assertEqual(self.types("reviews"), ["review"])
        self.assertEqual(self.types("completed"), ["status_change"])
        self.assertEqual(len(self.types("all")), 3)

    def test_feed_page_filter_and_review_excerpt(self):
        response = self.client.get(reverse("library:feed") + "?filter=reviews")

        self.assertEqual(response.context["selected_filter"], "reviews")
        self.assertContains(response, "Чудова гра")
        self.assertContains(response, "Сьогодні")

        response = self.client.get(reverse("library:feed") + "?filter=unknown")
        self.assertEqual(response.context["selected_filter"], "all")

    def test_completed_event_is_highlighted(self):
        response = self.client.get(reverse("library:feed"))

        self.assertContains(response, "is-celebrate")
        self.assertContains(response, "★ Пройдено")

    def test_day_label(self):
        from library.templatetags.library_extras import day_label

        now = timezone.now()
        self.assertEqual(day_label(now), "Сьогодні")
        self.assertEqual(day_label(now - timedelta(days=1)), "Вчора")
        self.assertRegex(day_label(now - timedelta(days=400)), r"^\d{1,2} [а-яі]+ \d{4}$")

