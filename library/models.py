from django.db import models


class Role(models.Model):
    id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=50)

    class Meta:
        managed = False
        db_table = 'roles'

    def __str__(self):
        return self.name


class User(models.Model):
    id = models.AutoField(primary_key=True)
    role = models.ForeignKey(
        Role,
        on_delete=models.DO_NOTHING,
        db_column='role_id',
        related_name='users'
    )
    username = models.CharField(max_length=50, unique=True)
    # NULL, а не "" — інакше унікальний індекс не дасть двом акаунтам без email (Steam) існувати.
    email = models.CharField(max_length=100, unique=True, null=True, blank=True)
    email_verified_at = models.DateTimeField(null=True, blank=True)
    # Для акаунтів зі Steam/Google — "непридатний" хеш (make_password(None)): паролем не увійти.
    password_hash = models.CharField(max_length=255)
    avatar = models.ImageField(upload_to='avatars/', null=True, blank=True)
    is_private = models.BooleanField(default=False)
    show_activity = models.BooleanField(default=True)
    created_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = 'users'

    def __str__(self):
        return self.username

    @property
    def has_usable_password(self):
        from django.contrib.auth.hashers import is_password_usable
        return is_password_usable(self.password_hash)

    @property
    def is_email_verified(self):
        return bool(self.email and self.email_verified_at)


class Game(models.Model):
    id = models.AutoField(primary_key=True)
    steam_appid = models.CharField(max_length=100, unique=True, blank=True, null=True)
    title = models.CharField(max_length=150)
    description = models.TextField(blank=True, null=True)
    developer = models.CharField(max_length=100, blank=True, null=True)
    release_date = models.DateField(blank=True, null=True)
    poster = models.ImageField(upload_to='game_posters/', null=True, blank=True)
    created_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = 'games'

    def __str__(self):
        return self.title


class Genre(models.Model):
    id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=50)

    class Meta:
        managed = False
        db_table = 'genres'

    def __str__(self):
        return self.name


class GameGenre(models.Model):
    game = models.ForeignKey(
        Game,
        on_delete=models.DO_NOTHING,
        db_column='game_id',
        related_name='game_genres'
    )
    genre = models.ForeignKey(
        Genre,
        on_delete=models.DO_NOTHING,
        db_column='genre_id',
        related_name='game_genres'
    )

    class Meta:
        managed = False
        db_table = 'game_genres'
        unique_together = (('game', 'genre'),)

    def __str__(self):
        return f'{self.game} - {self.genre}'


class GameRequest(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Очікує'),
        ('approved', 'Схвалено'),
        ('rejected', 'Відхилено'),
    ]

    id = models.AutoField(primary_key=True)
    title = models.CharField(max_length=150)
    description = models.TextField(blank=True, null=True)
    steam_appid = models.CharField(max_length=100, blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES)
    created_at = models.DateTimeField()
    reviewed_at = models.DateTimeField(blank=True, null=True)

    user = models.ForeignKey(
        User,
        on_delete=models.DO_NOTHING,
        db_column='user_id',
        related_name='game_requests'
    )
    moderator = models.ForeignKey(
        User,
        on_delete=models.DO_NOTHING,
        db_column='moderator_id',
        blank=True,
        null=True,
        related_name='moderated_requests'
    )

    class Meta:
        managed = False
        db_table = 'game_requests'

    def __str__(self):
        return self.title


class LibraryEntry(models.Model):
    STATUS_CHOICES = [
        ('planned', 'Планую'),
        ('playing', 'Граю'),
        ('completed', 'Пройдено'),
        ('paused', 'Відкладено'),
        ('dropped', 'Закинуто'),
    ]

    id = models.AutoField(primary_key=True)
    status = models.CharField(max_length=30, choices=STATUS_CHOICES)
    added_at = models.DateTimeField()

    user = models.ForeignKey(
        User,
        on_delete=models.DO_NOTHING,
        db_column='user_id',
        related_name='library_entries'
    )
    game = models.ForeignKey(
        Game,
        on_delete=models.DO_NOTHING,
        db_column='game_id',
        related_name='library_entries'
    )

    class Meta:
        managed = False
        db_table = 'library_entries'
        unique_together = (('user', 'game'),)

    def __str__(self):
        return f'{self.user.username} - {self.game.title}'


class Review(models.Model):
    id = models.AutoField(primary_key=True)
    score = models.PositiveSmallIntegerField()
    text = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField(blank=True, null=True)

    user = models.ForeignKey(
        User,
        on_delete=models.DO_NOTHING,
        db_column='user_id',
        related_name='reviews'
    )
    game = models.ForeignKey(
        Game,
        on_delete=models.DO_NOTHING,
        db_column='game_id',
        related_name='reviews'
    )

    class Meta:
        managed = False
        db_table = 'reviews'
        unique_together = (('user', 'game'),)

    def __str__(self):
        return f'{self.user.username} - {self.game.title} ({self.score})'


class SocialConnection(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Очікує'),
        ('accepted', 'Підтверджено'),
        ('rejected', 'Відхилено'),
    ]

    id = models.AutoField(primary_key=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES)
    created_at = models.DateTimeField()

    sender = models.ForeignKey(
        User,
        on_delete=models.DO_NOTHING,
        db_column='sender_id',
        related_name='sent_connections'
    )
    receiver = models.ForeignKey(
        User,
        on_delete=models.DO_NOTHING,
        db_column='receiver_id',
        related_name='received_connections'
    )

    class Meta:
        managed = False
        db_table = 'social_connections'
        unique_together = (('sender', 'receiver'),)

    def __str__(self):
        return f'{self.sender.username} -> {self.receiver.username}'


class DismissedRecommendation(models.Model):
    """Гра, яку користувач приховав із рекомендацій ("Не цікаво")."""

    id = models.AutoField(primary_key=True)
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        db_column='user_id',
        related_name='dismissed_recommendations'
    )
    game = models.ForeignKey(
        Game,
        on_delete=models.CASCADE,
        db_column='game_id',
        related_name='dismissed_recommendations'
    )
    created_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = 'dismissed_recommendations'
        unique_together = (('user', 'game'),)

    def __str__(self):
        return f'{self.user.username} - {self.game.title}'


class ExternalAccount(models.Model):
    id = models.AutoField(primary_key=True)
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        db_column="user_id",
        related_name="external_accounts"
    )
    provider = models.CharField(max_length=30)
    external_user_id = models.CharField(max_length=100)
    username = models.CharField(max_length=100, blank=True, null=True)
    profile_url = models.CharField(max_length=255, blank=True, null=True)
    avatar_url = models.CharField(max_length=255, blank=True, null=True)
    connected_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "external_accounts"
        managed = False
        unique_together = (
            ("provider", "external_user_id"),
            ("user", "provider"),
        )

    def __str__(self):
        return f"{self.provider}: {self.username or self.external_user_id}"


class ExternalLibraryItem(models.Model):
    id = models.AutoField(primary_key=True)
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        db_column="user_id",
        related_name="external_library_items"
    )
    external_account = models.ForeignKey(
        ExternalAccount,
        on_delete=models.CASCADE,
        db_column="external_account_id",
        related_name="library_items"
    )
    provider = models.CharField(max_length=30)
    external_game_id = models.CharField(max_length=100)
    game_title = models.CharField(max_length=150)
    playtime_minutes = models.IntegerField(default=0)
    playtime_2weeks_minutes = models.IntegerField(default=0)
    last_played_at = models.DateTimeField(blank=True, null=True)
    launch_url = models.CharField(max_length=255, blank=True, null=True)
    synced_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "external_library_items"
        managed = False
        unique_together = (
            ("user", "provider", "external_game_id"),
        )

    @property
    def playtime_hours(self):
        return round((self.playtime_minutes or 0) / 60, 1)

    @property
    def playtime_2weeks_hours(self):
        return round((self.playtime_2weeks_minutes or 0) / 60, 1)

    @property
    def cover_url(self):
        # Точна обкладинка зі Steam Store, якщо її підвантажено (attach_steam_apps),
        # інакше — CDN за appid (для частини нових ігор там нічого немає).
        steam_app = getattr(self, "steam_app", None)
        if steam_app is not None and steam_app.header_image:
            return steam_app.header_image

        from library.services.steam_service import steam_cover_url
        return steam_cover_url(self.external_game_id)

    @property
    def store_url(self):
        from library.services.steam_service import steam_store_url
        return steam_store_url(self.external_game_id)

    def __str__(self):
        return f"{self.provider}: {self.game_title}"


class SteamApp(models.Model):
    """Дані гри зі Steam Store, спільні для всіх користувачів (обкладинка, жанри)."""

    appid = models.CharField(max_length=20, primary_key=True)
    name = models.CharField(max_length=255, blank=True, null=True)
    header_image = models.CharField(max_length=500, blank=True, null=True)
    genres = models.CharField(max_length=500, blank=True, default="")
    found = models.BooleanField(default=True)
    fetched_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = "steam_apps"

    def __str__(self):
        return f"{self.appid}: {self.name or '?'}"

    @property
    def genre_list(self):
        return [g.strip() for g in self.genres.split(",") if g.strip()]


class ActivityEvent(models.Model):
    """Подія для стрічки активності (див. library/services/activity.py)."""

    LIBRARY_ADD = "library_add"
    STATUS_CHANGE = "status_change"
    REVIEW = "review"
    STEAM_IMPORT = "steam_import"
    FRIENDSHIP = "friendship"
    GAME_APPROVED = "game_approved"

    id = models.AutoField(primary_key=True)
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, db_column="user_id", related_name="activity_events"
    )
    event_type = models.CharField(max_length=30)
    game = models.ForeignKey(
        Game, on_delete=models.CASCADE, db_column="game_id", null=True, blank=True,
        related_name="activity_events",
    )
    target_user = models.ForeignKey(
        User, on_delete=models.CASCADE, db_column="target_user_id", null=True, blank=True,
        related_name="activity_events_as_target",
    )
    status = models.CharField(max_length=30, blank=True, null=True)
    score = models.SmallIntegerField(blank=True, null=True)
    item_count = models.IntegerField(blank=True, null=True)
    created_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = "activity_events"

    def __str__(self):
        return f"{self.user_id} {self.event_type} {self.game_id or ''}"

