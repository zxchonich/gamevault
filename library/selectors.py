"""Спільні запити й підготовка даних для view: бібліотеки, профілі, жанри, статуси."""

from django.db import models

from .access import friend_ids
from .models import ExternalLibraryItem, Game, GameGenre, Genre, LibraryEntry, Review, SteamApp, User

STATUSES = [value for value, _ in LibraryEntry.STATUS_CHOICES]

# Підписи статусів: про себе ("Планую") і про іншого користувача ("Планує").
STATUS_LABELS = dict(LibraryEntry.STATUS_CHOICES)
STATUS_LABELS_OTHER = {**STATUS_LABELS, "planned": "Планує", "playing": "Грає"}

# Кольори плашок для ігор без постера: (фон, текст). Колір стабільний для гри (за id).
COVER_PALETTE = [
    ("#7C5CFF", "#FFFFFF"),
    ("#FFB547", "#17151F"),
    ("#4CD6A0", "#17151F"),
    ("#FF6B5A", "#17151F"),
    ("#3DA5FF", "#17151F"),
    ("#FF7AC6", "#17151F"),
]

# Кольори смужок статусів на сторінці гри.
STATUS_COLORS = {
    "playing": "#3DA5FF",
    "completed": "#C8F031",
    "planned": "#7C5CFF",
    "paused": "#FFB547",
    "dropped": "#FF6B5A",
}

LIBRARY_SORTS = {
    "title": ("game__title",),
    "oldest": ("added_at",),
    "newest": ("-added_at",),
}


def get_status_label(status, other=False):
    return (STATUS_LABELS_OTHER if other else STATUS_LABELS).get(status, status)


def status_choices(other=False):
    return [{"value": value, "label": get_status_label(value, other)} for value in STATUSES]


def cover_colors(game):
    return COVER_PALETTE[(game.id or 0) % len(COVER_PALETTE)]


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
        "recent_entries": entries[:8],
        "recent_reviews": reviews[:4],
        "status_breakdown": [
            {
                "status": status,
                "label": STATUS_LABELS[status],
                "count": count,
                "percent": round(count / library_count * 100) if library_count else 0,
                "color": STATUS_COLORS[status],
            }
            for status, count in counts.items()
        ],
    }
    for status, count in counts.items():
        stats[f"{status}_count"] = count
        stats[f"{status}_percent"] = int(count / library_count * 100) if library_count else 0

    return stats


# --- Сторінка гри --------------------------------------------------------------

def game_page_stats(game, viewer=None, similar_limit=6):
    """Дані для сторінки гри: хто грає, розподіл оцінок, друзі з грою, схожі ігри, фон."""
    entries = LibraryEntry.objects.filter(game=game)
    counts = status_counts(entries)
    players_total = sum(counts.values())
    players = [
        {
            "status": status,
            "label": STATUS_LABELS_OTHER[status],
            "count": count,
            "percent": round(count / players_total * 100) if players_total else 0,
            "color": STATUS_COLORS[status],
        }
        for status, count in counts.items()
    ]

    score_counts = dict(
        Review.objects.filter(game=game).values("score").annotate(n=models.Count("id")).values_list("score", "n")
    )
    max_count = max(score_counts.values(), default=0)
    score_bars = [
        {"score": score, "count": score_counts.get(score, 0),
         "height": round(score_counts.get(score, 0) / max_count * 100) if max_count else 0}
        for score in range(1, 11)
    ]

    friends_with_game = []
    if viewer is not None:
        ids = friend_ids(viewer)
        hours = {}
        if game.steam_appid and ids:
            hours = dict(
                ExternalLibraryItem.objects
                .filter(user_id__in=ids, provider="steam", external_game_id=game.steam_appid)
                .values_list("user_id", "playtime_minutes")
            )
        statuses = dict(entries.filter(user_id__in=ids).values_list("user_id", "status"))
        for user in User.objects.filter(id__in=set(statuses) | set(hours)).order_by("username"):
            friends_with_game.append({
                "user": user,
                "status_label": STATUS_LABELS_OTHER.get(statuses.get(user.id), "Є в Steam"),
                "hours": round(hours[user.id] / 60) if hours.get(user.id) else None,
            })

    genre_ids = list(GameGenre.objects.filter(game=game).values_list("genre_id", flat=True))
    similar_ids = list(
        GameGenre.objects
        .filter(genre_id__in=genre_ids)
        .exclude(game_id=game.id)
        .values("game_id")
        .annotate(shared=models.Count("genre_id"))
        .order_by("-shared", "game_id")
        .values_list("game_id", flat=True)[:similar_limit]
    )
    similar = {g.id: g for g in Game.objects.filter(id__in=similar_ids).annotate(avg_score=models.Avg("reviews__score"))}
    similar_games = attach_visible_genres_to_games([similar[i] for i in similar_ids if i in similar])

    steam_header = None
    if game.steam_appid:
        steam_header = (
            SteamApp.objects.filter(appid=game.steam_appid, found=True).values_list("header_image", flat=True).first()
        )

    hero_bg, hero_ink = cover_colors(game)
    return {
        "players": players,
        "players_total": players_total,
        "score_bars": score_bars,
        "friends_with_game": friends_with_game,
        "similar_games": similar_games,
        "hero_image": game.poster.url if game.poster else steam_header,
        "hero_bg": hero_bg,
        "hero_ink": hero_ink,
    }

