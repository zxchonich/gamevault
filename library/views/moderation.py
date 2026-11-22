"""Заявки користувачів на додавання ігор і їх модерація."""

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from ..access import admin_required, library_login_required
from ..forms import GameRequestForm
from ..models import Game, GameRequest, Genre
from ..selectors import set_game_genres
from ..services import activity
from ..services.steam_service import (
    SteamError,
    download_steam_poster,
    fetch_store_details,
    link_game_to_steam_owners,
)


def steam_link_message(added):
    return f" Додано до бібліотек власників у Steam: {added}." if added else ""


@library_login_required
def request_game(request):
    user = request.library_user

    if request.method == "POST":
        form = GameRequestForm(request.POST)
        if form.is_valid():
            GameRequest.objects.create(
                user=user,
                title=form.cleaned_data["title"],
                description=form.cleaned_data["description"],
                status="pending",
                created_at=timezone.now(),
            )
            messages.success(request, "Заявку на додавання гри надіслано.")
            return redirect("library:my_requests")

        messages.error(request, form.first_error())

    return render(request, "library/request_game.html", {"user": user})


@library_login_required
def my_requests(request):
    requests = GameRequest.objects.filter(user=request.library_user).select_related("moderator").order_by("-created_at")

    return render(request, "library/my_requests.html", {
        "requests": requests,
        "total_requests_count": requests.count(),
        "pending_requests_count": requests.filter(status="pending").count(),
        "approved_requests_count": requests.filter(status="approved").count(),
    })


@admin_required
def moderation(request):
    by_status = GameRequest.objects.select_related("user", "moderator").order_by("-created_at")

    return render(request, "library/moderation.html", {
        "pending_requests": by_status.filter(status="pending"),
        "approved_requests": by_status.filter(status="approved")[:10],
        "rejected_requests": by_status.filter(status="rejected")[:10],
        "genres": Genre.objects.all().order_by("name"),
    })


def _fill_from_steam(game):
    """Доповнює нову гру даними Steam Store. Повертає примітку для повідомлення."""
    try:
        details = fetch_store_details(game.steam_appid)
    except SteamError as exc:
        return f" Дані Steam не отримано: {exc}"

    game.description = game.description or details["description"]
    game.developer = details["developer"] or None
    game.release_date = details["release_date"]
    if not download_steam_poster(game, details["header_image"]):
        return " Постер зі Steam завантажити не вдалося."
    return ""


@require_POST
@admin_required
def approve_request(request, request_id):
    game_request = get_object_or_404(GameRequest, id=request_id)

    if game_request.status != "pending":
        return redirect("library:moderation")

    appid = game_request.steam_appid
    game_request.status = "approved"
    game_request.moderator = request.library_user
    game_request.reviewed_at = timezone.now()

    existing_game = Game.objects.filter(steam_appid=appid).first() if appid else None
    if existing_game:
        game_request.save()
        messages.info(
            request,
            f'Заявку "{game_request.title}" схвалено, але гра з цим Steam AppID '
            f'вже є в каталозі ("{existing_game.title}").'
        )
        return redirect("library:moderation")

    game = Game(
        title=game_request.title,
        description=game_request.description,
        steam_appid=appid or None,
        created_at=timezone.now(),
    )
    steam_note = _fill_from_steam(game) if appid else ""
    game.save()

    set_game_genres(game, request.POST.getlist("genres"))
    game_request.save()
    activity.record_game_approved(game_request.user, game)
    added = link_game_to_steam_owners(game) if appid else 0

    messages.success(
        request,
        f'Заявку "{game_request.title}" схвалено. Гру додано до каталогу.' + steam_link_message(added) + steam_note,
    )
    return redirect("library:moderation")


@require_POST
@admin_required
def reject_request(request, request_id):
    game_request = get_object_or_404(GameRequest, id=request_id)

    if game_request.status == "pending":
        game_request.status = "rejected"
        game_request.moderator = request.library_user
        game_request.reviewed_at = timezone.now()
        game_request.save()
        messages.success(request, f'Заявку "{game_request.title}" відхилено.')

    return redirect("library:moderation")
