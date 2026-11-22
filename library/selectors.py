"""Спільні запити й підготовка даних для view: бібліотеки, профілі, жанри, статуси."""

from django.db import models

from .access import friend_ids
from .models import GameGenre, Genre, LibraryEntry, Review

STATUSES = [value for value, _ in LibraryEntry.STATUS_CHOICES]

# Підписи статусів: про себе ("Планую") і про іншого користувача ("Планує").
STATUS_LABELS = dict(LibraryEntry.STATUS_CHOICES)
STATUS_LABELS_OTHER = {**STATUS_LABELS, "planned": "Планує", "playing": "Грає"}

LIBRARY_SORTS = {
    "title": ("game__title",),
    "oldest": ("added_at",),
    "newest": ("-added_at",),
}


def get_status_label(status, other=False):
    return (STATUS_LABELS_OTHER if other else STATUS_LABELS).get(status, status)


def status_choices(other=False):
    return [{"value": value, "label": get_status_label(value, other)} for value in STATUSES]


def status_counts(entries):
    """{статус: кількість} одним запитом (усі статуси присутні, навіть нульові)."""
    counts = dict.fromkeys(STATUSES, 0)
    for row in entries.order_by().values("status").annotate(n=models.Count("id")):
        counts[row["status"]] = row["n"]
    return counts


# --- Жанри ---------------------------------------------------------------------

def attach_visible_genres_to_games(games, limit=3):
    game_list = list(games)
    game_ids = [game.id for game in game_list]

    if not game_ids:
        return game_list

    genre_links = list(GameGenre.objects.filter(game_id__in=game_ids).values("game_id", "genre_id"))
    genres_by_id = {
        genre.id: genre
        for genre in Genre.objects.filter(id__in={link["genre_id"] for link in genre_links}).order_by("name")
    }

    genres_by_game = {}
    for link in genre_links:
        genre = genres_by_id.get(link["genre_id"])
        if genre is not None:
            genres_by_game.setdefault(link["game_id"], []).append(genre)

    for game in game_list:
        game.visible_genres = genres_by_game.get(game.id, [])[:limit]

    return game_list


def attach_visible_genres_to_entries(entries, limit=3):
    """Для записів бібліотеки, рекомендацій тощо — усього, що має .game."""
    items = list(entries)
    attach_visible_genres_to_games([item.game for item in items], limit)
    return items


def set_game_genres(game, genre_ids):
    """Замінює жанри гри; невідомі id ігноруються."""
    valid_ids = set(
        Genre.objects.filter(id__in=[g for g in genre_ids if str(g).isdigit()]).values_list("id", flat=True)
    )
    GameGenre.objects.filter(game=game).delete()
    for genre_id in sorted(valid_ids):
        GameGenre.objects.create(game=game, genre_id=genre_id)


# --- Бібліотека ----------------------------------------------------------------

def library_context(request, owner, other=False):
    """Фільтри, сортування й лічильники бібліотеки owner (для моєї та чужої бібліотеки)."""
    query = request.GET.get("q", "").strip()
    selected_status = request.GET.get("status", "")
    selected_genres = request.GET.getlist("genres")
    sort = request.GET.get("sort", "newest")

    all_entries = LibraryEntry.objects.filter(user=owner).select_related("game")
    entries = all_entries

    if query:
        entries = entries.filter(game__title__icontains=query)
    if selected_status:
        entries = entries.filter(status=selected_status)
    for genre_id in selected_genres:
        entries = entries.filter(game__game_genres__genre_id=genre_id)

    entries = entries.order_by(*LIBRARY_SORTS.get(sort, LIBRARY_SORTS["newest"])).distinct()
    entries = list(entries)

    for entry in entries:
        entry.status_label = get_status_label(entry.status)

    counts = status_counts(all_entries)

    return {
        "entries": attach_visible_genres_to_entries(entries),
        "genres": Genre.objects.all().order_by("name"),
        "status_choices": status_choices(other),
        "query": query,
        "selected_status": selected_status,
        "selected_genres": selected_genres,
        "selected_sort": sort,
        "library_count": sum(counts.values()),
        **{f"{status}_count": count for status, count in counts.items()},
        "filtered_count": len(entries),
    }


# --- Профіль -------------------------------------------------------------------

def profile_stats(user):
    """Статистика профілю: лічильники, відсотки статусів, середня оцінка, останні записи."""
    entries = LibraryEntry.objects.filter(user=user).select_related("game").order_by("-added_at")
    reviews = Review.objects.filter(user=user).select_related("game").order_by("-created_at")

    counts = status_counts(entries)
    library_count = sum(counts.values())

    stats = {
        "library_count": library_count,
        "review_count": reviews.count(),
        "friends_count": len(friend_ids(user)),
        "average_score": reviews.aggregate(avg=models.Avg("score"))["avg"] or 0,
        "recent_entries": entries[:4],
        "recent_reviews": reviews[:3],
    }
    for status, count in counts.items():
        stats[f"{status}_count"] = count
        stats[f"{status}_percent"] = int(count / library_count * 100) if library_count else 0

    return stats
