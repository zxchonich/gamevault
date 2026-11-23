"""Адміністрування каталогу: ігри, жанри, видалення рецензій."""

from django.contrib import messages
from django.db import models
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from ..access import admin_required, is_admin_user, library_login_required, redirect_to_next
from ..forms import GameForm, GenreForm
from ..models import DismissedRecommendation, Game, GameGenre, Genre, LibraryEntry, Review, SteamApp
from ..selectors import set_game_genres
from ..services.steam_catalog import block_appid
from ..storage import delete_unused_file
from ..services import activity
from ..services.steam_service import (
    SteamError,
    download_steam_poster,
    fetch_store_details,
    is_valid_appid,
    link_game_to_steam_owners,
)
from .moderation import steam_link_message

ADD_TITLES = ("Додати гру", "Додати гру")
EDIT_TITLES = ("Редагувати гру", "Зберегти зміни")


def _initial_form_data(game=None):
    return {
        "title": game.title if game else "",
        "description": (game.description or "") if game else "",
        "developer": (game.developer or "") if game else "",
        "release_date": game.release_date.isoformat() if game and game.release_date else "",
        "steam_appid": (game.steam_appid or "") if game else "",
    }


def _apply_steam_prefill(request, form_data):
    """Заповнює форму гри даними Steam Store, якщо передано ?steam_appid=..."""
    appid = request.GET.get("steam_appid", "").strip()
    if not appid:
        return

    if not is_valid_appid(appid):
        messages.error(request, "Steam AppID має складатися лише з цифр.")
        return

    form_data["steam_appid"] = appid

    try:
        details = fetch_store_details(appid)
    except SteamError as exc:
        messages.error(request, str(exc))
        return

    for field in ("title", "description", "developer"):
        if details[field]:
            form_data[field] = details[field]
    if details["release_date"]:
        form_data["release_date"] = details["release_date"].isoformat()

    form_data["steam_header_image"] = details["header_image"]
    form_data["download_steam_poster"] = True

    messages.info(request, "Дані заповнено зі Steam. Перевірте їх і збережіть форму.")


def _render_game_form(request, game, form_data, selected_genre_ids, titles):
    form_title, button_text = titles
    return render(request, "library/admin_game_form.html", {
        "game": game,
        "form_data": form_data,
        "genres": Genre.objects.all().order_by("name"),
        "selected_genre_ids": selected_genre_ids,
        "form_title": form_title,
        "button_text": button_text,
    })


def _save_game(request, game, form):
    """Зберігає гру з валідної форми. Повертає кількість бібліотек, куди гру додано через Steam."""
    data = form.cleaned_data
    old_appid = game.steam_appid

    game.title = data["title"]
    game.description = data["description"]
    game.developer = data["developer"]
    game.release_date = data["release_date"]
    game.steam_appid = data["steam_appid"]

    old_poster = game.poster.name if game.poster else ""
    poster = request.FILES.get("poster")
    if poster:
        game.poster = poster
    elif data["download_steam_poster"] and game.steam_appid:
        if not download_steam_poster(game, data["steam_header_image"]):
            messages.warning(request, "Не вдалося завантажити постер зі Steam.")

    game.save()
    if game.steam_appid:
        # Адмін сам (повторно) додав гру — знімаємо її з «чорного списку» автоімпорту.
        SteamApp.objects.filter(appid=game.steam_appid, blocked=True).update(blocked=False)
    if old_poster and old_poster != (game.poster.name if game.poster else ""):
        delete_unused_file(Game, "poster", old_poster)
    set_game_genres(game, request.POST.getlist("genres"))

    if game.steam_appid and game.steam_appid != old_appid:
        return link_game_to_steam_owners(game)
    return 0


MAX_POSTER_SIZE = 10 * 1024 * 1024


def _poster_error(poster):
    """Текст помилки для завантаженого постера або None."""
    if not poster:
        return None
    if poster.size > MAX_POSTER_SIZE:
        return "Постер завеликий — до 10 МБ."
    from django import forms

    try:
        forms.ImageField().clean(poster)
    except forms.ValidationError:
        return "Постер має бути зображенням (JPG, PNG, WebP)."
    poster.seek(0)
    return None


def _game_form_view(request, game, titles, success_message):
    if request.method == "POST":
        form = GameForm(request.POST, game=game)
        poster_error = _poster_error(request.FILES.get("poster"))
        if poster_error or not form.is_valid():
            messages.error(request, poster_error or form.first_error())
            return _render_game_form(request, game, form.form_data(), form.selected_genre_ids(), titles)

        game = game or Game(created_at=timezone.now())
        added = _save_game(request, game, form)
        messages.success(request, success_message + steam_link_message(added))
        return redirect("library:game_detail", game_id=game.id)

    form_data = _initial_form_data(game)
    _apply_steam_prefill(request, form_data)
    selected = set(GameGenre.objects.filter(game=game).values_list("genre_id", flat=True)) if game else set()
    return _render_game_form(request, game, form_data, selected, titles)


@admin_required
def admin_game_add(request):
    return _game_form_view(request, None, ADD_TITLES, "Гру додано до каталогу.")


@admin_required
def admin_game_edit(request, game_id):
    game = get_object_or_404(Game, id=game_id)
    return _game_form_view(request, game, EDIT_TITLES, "Гру оновлено.")


@require_POST
@admin_required
def admin_game_delete(request, game_id):
    game = get_object_or_404(Game, id=game_id)

    # Зв'язки з DO_NOTHING (застаріла схема) прибираємо вручну; решта — каскадом.
    GameGenre.objects.filter(game=game).delete()
    LibraryEntry.objects.filter(game=game).delete()
    Review.objects.filter(game=game).delete()
    DismissedRecommendation.objects.filter(game=game).delete()
    poster = game.poster.name if game.poster else ""
    appid = game.steam_appid
    game.delete()
    delete_unused_file(Game, "poster", poster)
    block_appid(appid)  # інакше синхронізація Steam додала б гру в каталог знову

    messages.success(request, "Гру видалено з каталогу.")
    return redirect("library:game_list")


@require_POST
@library_login_required
def admin_review_delete(request, review_id):
    """Видалити рецензію може її автор або адміністратор."""
    user = request.library_user
    review = get_object_or_404(Review, id=review_id)
    game_id = review.game_id

    if review.user_id != user.id and not is_admin_user(user):
        messages.error(request, "Ви не можете видалити цю рецензію.")
        return redirect("library:game_detail", game_id=game_id)

    activity.forget_review_activity(review.user, review.game)
    review.delete()
    messages.success(request, "Рецензію видалено.")

    return redirect_to_next(request, "library:game_detail", game_id=game_id)


@admin_required
def admin_genre_list(request):
    if request.method == "POST":
        form = GenreForm(request.POST)
        if form.is_valid():
            name = form.cleaned_data["name"]
            Genre.objects.create(name=name)
            messages.success(request, f'Жанр "{name}" додано.')
        else:
            messages.error(request, form.first_error())
        return redirect("library:admin_genre_list")

    genres = Genre.objects.annotate(games_count=models.Count("game_genres__game_id")).order_by("name")

    return render(request, "library/admin_genre_list.html", {
        "genres_data": [{"genre": genre, "games_count": genre.games_count} for genre in genres],
        "genres_count": len(genres),
    })


@require_POST
@admin_required
def admin_genre_delete(request, genre_id):
    genre = get_object_or_404(Genre, id=genre_id)

    if GameGenre.objects.filter(genre=genre).exists():
        messages.error(request, f'Жанр "{genre.name}" не можна видалити, бо він використовується в іграх.')
    else:
        genre_name = genre.name
        genre.delete()
        messages.success(request, f'Жанр "{genre_name}" видалено.')

    return redirect("library:admin_genre_list")
