"""Головна, каталог ігор і сторінка гри."""

from django.core.paginator import Paginator
from django.db import models
from django.shortcuts import get_object_or_404, render

from ..access import friend_ids, get_current_user
from ..models import Game, Genre, LibraryEntry, Review, User
from ..selectors import (
    attach_visible_genres_to_entries,
    attach_visible_genres_to_games,
    game_page_stats,
    get_status_label,
)
from ..services import activity
from ..services.recommendations import build_recommendations
from ..services.steam_service import steam_items_by_appid

GAMES_PAGE_SIZE = 24  # ділиться на 2/3/4/6/8 колонок .gv-grid-24
GAME_SORTS = {
    "newest": ("-created_at",),
    "rating": ("-avg_score", "title"),
    "title": ("title",),
}


def _games_with_rating():
    return Game.objects.annotate(avg_score=models.Avg("reviews__score"))


def home(request):
    current_user = get_current_user(request)

    games = _games_with_rating().order_by("-created_at")[:6]
    top_rated_games = _games_with_rating().filter(avg_score__isnull=False).order_by("-avg_score", "title")[:5]
    most_added_games = (
        Game.objects
        .annotate(library_count=models.Count("library_entries"))
        .filter(library_count__gt=0)
        .order_by("-library_count", "title")[:5]
    )
    active_users = (
        User.objects
        .annotate(
            library_count=models.Count("library_entries", distinct=True),
            review_count=models.Count("reviews", distinct=True),
            activity_score=(
                models.Count("library_entries", distinct=True) * 10
                + models.Count("reviews", distinct=True) * 5
            ),
        )
        .order_by("-activity_score", "-library_count", "-review_count", "username")[:5]
    )

    context = {
        "current_user": current_user,
        "home_recommendations": [],
        "home_feed": [],
        "home_now_playing": [],
        "games": attach_visible_genres_to_games(games),
        "genres": Genre.objects.all().order_by("name")[:10],
        "top_rated_games": attach_visible_genres_to_games(top_rated_games),
        "most_added_games": attach_visible_genres_to_games(most_added_games),
        "active_users": active_users,
        "total_games_count": Game.objects.count(),
        "total_genres_count": Genre.objects.count(),
        "total_users_count": User.objects.count(),
        "total_reviews_count": Review.objects.count(),
        "total_library_entries_count": LibraryEntry.objects.count(),
        "user_library_count": 0,
        "user_review_count": 0,
        "user_friends_count": 0,
    }

    if current_user is not None:
        context.update({
            "home_feed": activity.build_feed(current_user, limit=8)[:5],
            "home_now_playing": activity.now_playing(current_user, limit=4),
            "home_recommendations": attach_visible_genres_to_entries(
                build_recommendations(current_user, limit=3).recommendations
            ),
            "user_library_count": LibraryEntry.objects.filter(user=current_user).count(),
            "user_review_count": Review.objects.filter(user=current_user).count(),
            "user_friends_count": len(friend_ids(current_user)),
        })

    return render(request, "library/home.html", context)


def game_list(request):
    query = request.GET.get("q", "")
    selected_genres = request.GET.getlist("genres")
    sort = request.GET.get("sort", "title")

    games = _games_with_rating()
    if query:
        games = games.filter(title__icontains=query)
    for genre_id in selected_genres:
        games = games.filter(game_genres__genre_id=genre_id)
    games = games.order_by(*GAME_SORTS.get(sort, GAME_SORTS["title"])).distinct()

    page_obj = Paginator(games, GAMES_PAGE_SIZE).get_page(request.GET.get("page"))
    page_obj.object_list = attach_visible_genres_to_games(page_obj.object_list)

    return render(request, "library/game_list.html", {
        "games": page_obj,
        "page_obj": page_obj,
        "genres": Genre.objects.all().order_by("name"),
        "query": query,
        "selected_genres": selected_genres,
        "selected_sort": sort,
        "total_games_count": Game.objects.count(),
        "games_with_reviews_count": Game.objects.filter(reviews__isnull=False).distinct().count(),
        "genres_count": Genre.objects.count(),
    })


def game_detail(request, game_id):
    game = get_object_or_404(Game, id=game_id)
    reviews = Review.objects.filter(game=game).select_related("user").order_by("-created_at")
    user = get_current_user(request)

    library_entry = None
    user_review = None
    if user is not None:
        library_entry = LibraryEntry.objects.filter(user=user, game=game).first()
        user_review = Review.objects.filter(user=user, game=game).first()

    return render(request, "library/game_detail.html", {
        "game": game,
        "steam_item": steam_items_by_appid(user, [game.steam_appid]).get(game.steam_appid),
        "reviews": reviews,
        "game_genres": Genre.objects.filter(game_genres__game=game).order_by("name"),
        "library_entry": library_entry,
        "user_review": user_review,
        "average_score": reviews.aggregate(avg=models.Avg("score"))["avg"] or 0,
        "reviews_count": reviews.count(),
        "user_review_status": "Додана" if user_review else "Не додана",
        "library_status_label": get_status_label(library_entry.status) if library_entry else None,
        **game_page_stats(game, user),
    })
