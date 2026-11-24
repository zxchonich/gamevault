from django.urls import path

from .views import accounts, achievements, catalog, catalog_admin, discover, google, library, moderation, social, steam

app_name = 'library'

urlpatterns = [
    # Каталог
    path('', catalog.home, name='home'),
    path('games/', catalog.game_list, name='game_list'),
    path('games/<int:game_id>/', catalog.game_detail, name='game_detail'),

    # Бібліотека та рецензії
    path('my-library/', library.my_library, name='my_library'),
    path('games/<int:game_id>/add/', library.add_to_library, name='add_to_library'),
    path('library/<int:entry_id>/status/', library.update_library_status, name='update_library_status'),
    path('library/<int:entry_id>/delete/', library.delete_library_entry, name='delete_library_entry'),
    path('games/<int:game_id>/review/', library.add_review, name='add_review'),
    path('my-reviews/', library.my_reviews, name='my_reviews'),
    path('users/<int:user_id>/library/', library.user_library, name='user_library'),

    # Заявки на ігри та модерація
    path('request-game/', moderation.request_game, name='request_game'),
    path('my-requests/', moderation.my_requests, name='my_requests'),
    path('moderation/', moderation.moderation, name='moderation'),
    path('moderation/<int:request_id>/approve/', moderation.approve_request, name='approve_request'),
    path('moderation/<int:request_id>/reject/', moderation.reject_request, name='reject_request'),

    # Рекомендації та стрічка
    path('recommendations/', discover.recommendations, name='recommendations'),
    path('recommendations/<int:game_id>/dismiss/', discover.dismiss_recommendation, name='dismiss_recommendation'),
    path('recommendations/<int:game_id>/restore/', discover.restore_recommendation, name='restore_recommendation'),
    path('feed/', discover.feed, name='feed'),
    path('notifications/', discover.notifications_page, name='notifications'),
    path('notifications/read/', discover.notifications_mark_read, name='notifications_mark_read'),

    # Користувачі, друзі, профілі
    path('users/', social.user_list, name='user_list'),
    path('users/<int:user_id>/add-friend/', social.add_friend, name='add_friend'),
    path('users/<int:user_id>/block/', social.block_user, name='block_user'),
    path('users/<int:user_id>/unblock/', social.unblock_user, name='unblock_user'),
    path('friends/', social.friends, name='friends'),
    path('connections/<int:connection_id>/accept/', social.accept_connection, name='accept_connection'),
    path('connections/<int:connection_id>/reject/', social.reject_connection, name='reject_connection'),
    path('connections/<int:connection_id>/delete/', social.delete_connection, name='delete_connection'),
    path('users/<int:user_id>/profile/', social.user_profile, name='user_profile'),
    path('profile/', social.profile, name='profile'),
    path('edit-profile/', social.edit_profile, name='edit_profile'),

    # Досягнення GameVault
    path('achievements/', achievements.my_achievements, name='my_achievements'),
    path('achievements/showcase/', achievements.save_showcase, name='save_showcase'),
    path('users/<int:user_id>/achievements/', achievements.user_achievements, name='user_achievements'),

    # Акаунт
    path('login/', accounts.login_view, name='login'),
    path('logout/', accounts.logout_view, name='logout'),
    path('register/', accounts.register_view, name='register'),
    path('register/verify/', accounts.verify_pending, name='verify_pending'),
    path('verify-email/<str:token>/', accounts.verify_email, name='verify_email'),
    path('password-reset/', accounts.password_reset_request, name='password_reset'),
    path('password-reset/<str:token>/', accounts.password_reset_confirm, name='password_reset_confirm'),

    # Адміністрування каталогу
    path('manage/games/add/', catalog_admin.admin_game_add, name='admin_game_add'),
    path('manage/games/<int:game_id>/edit/', catalog_admin.admin_game_edit, name='admin_game_edit'),
    path('manage/games/<int:game_id>/delete/', catalog_admin.admin_game_delete, name='admin_game_delete'),
    path('manage/reviews/<int:review_id>/delete/', catalog_admin.admin_review_delete, name='admin_review_delete'),
    path('manage/genres/', catalog_admin.admin_genre_list, name='admin_genre_list'),
    path('manage/genres/<int:genre_id>/delete/', catalog_admin.admin_genre_delete, name='admin_genre_delete'),

    # Steam
    path("google/connect/", google.google_connect, name="google_connect"),
    path("google/callback/", google.google_callback, name="google_callback"),
    path("google/disconnect/", google.google_disconnect, name="google_disconnect"),
    path("steam/connect/", steam.steam_connect, name="steam_connect"),
    path("steam/callback/", steam.steam_callback, name="steam_callback"),
    path("steam/disconnect/", steam.steam_disconnect, name="steam_disconnect"),
    path("steam/sync/", steam.steam_sync_library, name="steam_sync_library"),
    path("steam/library/", steam.steam_library, name="steam_library"),
    path("users/<int:user_id>/steam/", steam.user_steam_library, name="user_steam_library"),
    path("manage/steam-matching/", steam.admin_steam_matching, name="admin_steam_matching"),
    path("manage/steam-matching/<int:game_id>/link/", steam.admin_steam_link, name="admin_steam_link"),
]
