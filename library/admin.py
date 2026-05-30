from django.contrib import admin
from .models import (
    Role,
    User,
    Game,
    Genre,
    GameRequest,
    LibraryEntry,
    Review,
    SocialConnection,
    Recommendation,
)


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ('id', 'name')


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ('id', 'username', 'email', 'role', 'created_at')
    search_fields = ('username', 'email')


@admin.register(Game)
class GameAdmin(admin.ModelAdmin):
    list_display = ('id', 'title', 'developer', 'release_date', 'created_at')
    search_fields = ('title', 'developer')


@admin.register(Genre)
class GenreAdmin(admin.ModelAdmin):
    list_display = ('id', 'name')
    search_fields = ('name',)


#@admin.register(GameGenre)
#class GameGenreAdmin(admin.ModelAdmin):
#    list_display = ('game', 'genre')


@admin.register(GameRequest)
class GameRequestAdmin(admin.ModelAdmin):
    list_display = ('id', 'title', 'user', 'moderator', 'status', 'created_at', 'reviewed_at')
    list_filter = ('status',)
    search_fields = ('title', 'user__username')


@admin.register(LibraryEntry)
class LibraryEntryAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'game', 'status', 'added_at')
    list_filter = ('status',)
    search_fields = ('user__username', 'game__title')


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'game', 'score', 'created_at', 'updated_at')
    search_fields = ('user__username', 'game__title')


@admin.register(SocialConnection)
class SocialConnectionAdmin(admin.ModelAdmin):
    list_display = ('id', 'sender', 'receiver', 'status', 'created_at')
    list_filter = ('status',)


@admin.register(Recommendation)
class RecommendationAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'game', 'match_score', 'created_at')
    search_fields = ('user__username', 'game__title')