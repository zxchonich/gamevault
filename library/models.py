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
    username = models.CharField(max_length=50)
    email = models.CharField(max_length=100)
    password_hash = models.CharField(max_length=255)
    avatar = models.ImageField(upload_to='avatars/', null=True, blank=True)
    is_private = models.BooleanField(default=False)
    created_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = 'users'

    def __str__(self):
        return self.username


class Game(models.Model):
    id = models.AutoField(primary_key=True)
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


class Recommendation(models.Model):
    id = models.AutoField(primary_key=True)
    match_score = models.DecimalField(max_digits=5, decimal_places=2, blank=True, null=True)
    reason = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField()

    user = models.ForeignKey(
        User,
        on_delete=models.DO_NOTHING,
        db_column='user_id',
        related_name='recommendations'
    )
    game = models.ForeignKey(
        Game,
        on_delete=models.DO_NOTHING,
        db_column='game_id',
        related_name='recommendations'
    )

    class Meta:
        managed = False
        db_table = 'recommendations'

    def __str__(self):
        return f'{self.user.username} - {self.game.title}'