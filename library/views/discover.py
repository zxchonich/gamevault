"""Рекомендації та стрічка активності."""

from django.contrib import messages
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from ..access import friend_ids, library_login_required, redirect_to_next
from ..models import DismissedRecommendation, Game
from ..selectors import attach_visible_genres_to_entries
from ..services import activity
from ..services.recommendations import build_recommendations


@library_login_required
def recommendations(request):
    user = request.library_user
    result = build_recommendations(user)
    recommendations_list = attach_visible_genres_to_entries(result.recommendations)
    scores = [r.score for r in recommendations_list]

    return render(request, "library/recommendations.html", {
        "user": user,
        "recommendations": recommendations_list,
        "recommendations_count": len(recommendations_list),
        "best_match_score": max(scores, default=0),
        "average_match": sum(scores) / len(scores) if scores else 0,
        "is_fallback": result.is_fallback,
        "has_steam_signals": result.has_steam_signals,
        "dismissed": list(
            DismissedRecommendation.objects.filter(user=user).select_related("game").order_by("-created_at")
        ),
    })


@require_POST
@library_login_required
def dismiss_recommendation(request, game_id):
    game = get_object_or_404(Game, id=game_id)
    DismissedRecommendation.objects.get_or_create(
        user=request.library_user, game=game, defaults={"created_at": timezone.now()}
    )
    messages.info(request, f'Гру "{game.title}" більше не буде в рекомендаціях.')
    return redirect_to_next(request, "library:recommendations")


@require_POST
@library_login_required
def restore_recommendation(request, game_id):
    DismissedRecommendation.objects.filter(user=request.library_user, game_id=game_id).delete()
    messages.success(request, "Гру повернуто до рекомендацій.")
    return redirect_to_next(request, "library:recommendations")


@library_login_required
def feed(request):
    user = request.library_user

    try:
        page = max(1, int(request.GET.get("page", 1)))
    except ValueError:
        page = 1

    size = activity.FEED_PAGE_SIZE
    events = list(activity.feed_events(user)[(page - 1) * size:page * size + 1])

    return render(request, "library/feed.html", {
        "items": activity.group_events(events[:size]),
        "now_playing": activity.now_playing(user),
        "page": page,
        "has_more": len(events) > size,
        "has_friends": bool(friend_ids(user)),
    })
