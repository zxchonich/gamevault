from unittest import mock

from django.contrib.auth.hashers import make_password
from django.test import TestCase
from django.utils import timezone

from library.models import (
    ExternalAccount,
    ExternalLibraryItem,
    Game,
    LibraryEntry,
    Role,
    SocialConnection,
    User,
)

USER_ROLE_ID = 1
ADMIN_ROLE_ID = 2
DEFAULT_PASSWORD = "secret-pass-123"


class GameVaultTestCase(TestCase):
    """Базовий клас із фабриками даних. Ролі user/admin створює schema.sql.

    Справжні HTTP-запити (Steam) заборонені: тест має мокати їх явно,
    інакше впаде з AssertionError, а не піде непомітно в мережу."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        for target in ("requests.get", "requests.post"):
            patcher = mock.patch(target, side_effect=AssertionError(f"Справжній HTTP-запит у тесті: {target}"))
            patcher.start()
            cls.addClassCleanup(patcher.stop)

    def run(self, result=None):
        # Лічильники невдалих входів (кеш) не переносяться між тестами; run(), а не setUp(),
        # бо підкласи перевизначають setUp без super().
        from django.core.cache import cache

        cache.clear()
        return super().run(result)

    def make_user(self, username, admin=False, private=False, password=DEFAULT_PASSWORD):
        return User.objects.create(
            role=Role.objects.get(id=ADMIN_ROLE_ID if admin else USER_ROLE_ID),
            username=username,
            email=f"{username}@example.com",
            password_hash=make_password(password),
            is_private=private,
            created_at=timezone.now(),
        )

    def make_game(self, title, steam_appid=None):
        return Game.objects.create(title=title, steam_appid=steam_appid, created_at=timezone.now())

    def make_entry(self, user, game, status="planned"):
        return LibraryEntry.objects.create(user=user, game=game, status=status, added_at=timezone.now())

    def make_friends(self, user1, user2, status="accepted"):
        return SocialConnection.objects.create(
            sender=user1, receiver=user2, status=status, created_at=timezone.now()
        )

    def make_steam_account(self, user, steam_id="76561197960287930"):
        return ExternalAccount.objects.create(
            user=user,
            provider="steam",
            external_user_id=steam_id,
            username=f"steam_{user.username}",
            profile_url=f"https://steamcommunity.com/profiles/{steam_id}",
        )

    def make_steam_item(self, account, appid, title, playtime=0, playtime_2weeks=0):
        return ExternalLibraryItem.objects.create(
            user=account.user,
            external_account=account,
            provider="steam",
            external_game_id=str(appid),
            game_title=title,
            playtime_minutes=playtime,
            playtime_2weeks_minutes=playtime_2weeks,
            launch_url=f"steam://run/{appid}",
        )

    def login(self, user, client=None):
        client = client or self.client
        from library.access import SESSION_AUTH_KEY, session_auth_hash

        session = client.session
        session["library_user_id"] = user.id
        session[SESSION_AUTH_KEY] = session_auth_hash(user)
        session.save()
        return client

    def messages_of(self, response):
        return [str(m) for m in response.context["messages"]]
