"""Бібліотеки (моя та чужа), статуси, рецензії."""

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from ..access import block_state, can_view_profile, connection_between, library_login_required, redirect_to_next
from ..forms import ReviewForm, StatusForm
from ..models import Game, LibraryEntry, Review, User
from ..selectors import library_context
from ..services import activity
from ..services.steam_service import steam_items_by_appid
from .social import private_profile_response


@library_login_required
def my_library(request):
    user = request.library_user
    context = library_context(request, user)

    steam_items = steam_items_by_appid(user, [entry.game.steam_appid for entry in context["entries"]])
    for entry in context["entries"]:
        entry.steam_item = steam_items.get(entry.game.steam_appid)

    return render(request, "library/my_library.html", {"user": user, **context})


@library_login_required
def user_library(request, user_id):
    current_user = request.library_user
    profile_user = get_object_or_404(User, id=user_id)

    if current_user.id == profile_user.id:
        return redirect("library:my_library")

    connection = connection_between(current_user, profile_user)

    if not can_view_profile(current_user, profile_user):
        return private_profile_response(request, current_user, profile_user, connection)

    return render(request, "library/user_library.html", {
        "current_user": current_user,
        "profile_user": profile_user,
        "connection": connection,
        "block_state": block_state(current_user, profile_user),
        **library_context(request, profile_user, other=True),
    })


@require_POST
@library_login_required
def add_to_library(request, game_id):
    user = request.library_user
    game = get_object_or_404(Game, id=game_id)

    _, created = LibraryEntry.objects.get_or_create(
        user=user, game=game, defaults={"status": "planned", "added_at": timezone.now()}
    )

    if created:
        activity.record_library_add(user, game)
        messages.success(request, f'Гру "{game.title}" додано до бібліотеки.')
    else:
        messages.info(request, f'Гра "{game.title}" вже є у вашій бібліотеці.')

    return redirect("library:my_library")


@require_POST
@library_login_required
def update_library_status(request, entry_id):
    user = request.library_user
    entry = get_object_or_404(LibraryEntry, id=entry_id, user=user)
    form = StatusForm(request.POST)

    if form.is_valid():
        new_status = form.cleaned_data["status"]
        if new_status != entry.status:
            activity.record_status_change(user, entry.game, new_status)
        entry.status = new_status
        entry.save()
        messages.success(request, f'Статус гри "{entry.game.title}" оновлено.')
    else:
        messages.error(request, "Невідомий статус.")

    return redirect_to_next(request, "library:my_library")


@require_POST
@library_login_required
def delete_library_entry(request, entry_id):
    user = request.library_user
    entry = get_object_or_404(LibraryEntry, id=entry_id, user=user)
    game_title = entry.game.title

    Review.objects.filter(user=user, game=entry.game).delete()
    activity.forget_game_activity(user, entry.game)
    entry.delete()

    messages.success(request, f'Гру "{game_title}" видалено з бібліотеки. Рецензію до цієї гри також видалено.')
    return redirect("library:my_library")


@require_POST
@library_login_required
def add_review(request, game_id):
    user = request.library_user
    game = get_object_or_404(Game, id=game_id)
    form = ReviewForm(request.POST)

    if not form.is_valid():
        messages.error(request, form.first_error())
        return redirect("library:game_detail", game_id=game.id)

    score, text = form.cleaned_data["score"], form.cleaned_data["text"]
    review, created = Review.objects.get_or_create(
        user=user, game=game, defaults={"score": score, "text": text, "created_at": timezone.now()}
    )

    if created or review.score != score:
        activity.record_review(user, game, score)

    if created:
        messages.success(request, "Рецензію додано.")
    else:
        review.score = score
        review.text = text
        review.updated_at = timezone.now()
        review.save()
        messages.success(request, "Рецензію оновлено.")

    return redirect("library:game_detail", game_id=game.id)


@library_login_required
def my_reviews(request):
    reviews = Review.objects.filter(user=request.library_user).select_related("game").order_by("-created_at")
    return render(request, "library/my_reviews.html", {"reviews": reviews})
