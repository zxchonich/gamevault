"""Персональні рекомендації ігор.

Оцінка гри-кандидата (0–100) складається з трьох частин:
  * жанри (до 50) — збіг із профілем смаків користувача;
  * друзі (до 30) — гра є в бібліотеках / Steam друзів, їхні оцінки та години;
  * якість (до 20) — середня оцінка, згладжена за кількістю відгуків.

Профіль смаків: кожна гра користувача з каталогу дає сигнал (статус у бібліотеці,
власна оцінка, години в Steam), який додається до ваг усіх її жанрів.
Усі дані завантажуються фіксованою кількістю запитів, незалежно від розміру каталогу.
"""

import math
from dataclasses import dataclass, field

from django.db import models

from library.access import friend_ids as get_friend_ids
from library.models import (
    DismissedRecommendation,
    ExternalLibraryItem,
    Game,
    GameGenre,
    LibraryEntry,
    Review,
    SteamApp,
    User,
)
from library.services.steam_service import catalog_genre_index, map_steam_genres

STATUS_WEIGHTS = {
    "completed": 3.0,
    "playing": 2.0,
    "planned": 1.0,
    "paused": 0.5,
    "dropped": -2.0,
}

# Steam-ігри поза каталогом впливають на смаки через жанри Steam Store, але з меншою вагою:
# жанри Steam загальні (Action, Indie...), а таких ігор у бібліотеці може бути сотні.
STEAM_ONLY_FACTOR = 0.5

GENRE_POINTS = 50
FRIEND_POINTS = 30
QUALITY_POINTS = 20
MIN_SCORE = 15

# Згладжування середньої оцінки: до відгуків гри додаються RATING_PRIOR_COUNT "уявних"
# відгуків з нейтральною оцінкою. Фіксована оцінка, а не середня по каталогу: у малому
# каталозі з високими оцінками середня близька до 9 і майже нічого не згладжує.
RATING_PRIOR_COUNT = 3
PRIOR_RATING = 6.5


@dataclass
class GameRecommendation:
    game: Game
    score: int
    reasons: list = field(default_factory=list)
    genre_points: int = 0
    friend_points: int = 0
    quality_points: int = 0

    # Сумісність зі старим шаблоном (колись це були поля моделі Recommendation).
    @property
    def match_score(self):
        return self.score

    @property
    def reason(self):
        return "; ".join(self.reasons)


@dataclass
class RecommendationResult:
    recommendations: list
    is_fallback: bool = False
    has_steam_signals: bool = False


def review_weight(score):
    """8–10 підвищують інтерес до жанрів, 1–4 знижують, 5–7 нейтральні."""
    if score >= 8:
        return float(score - 7)
    if score <= 4:
        return float(score - 5)
    return 0.0


def steam_weight(minutes, minutes_2weeks=0):
    """Логарифм годин: 2 год і 200 год різняться, але не в 100 разів."""
    hours = (minutes or 0) / 60
    weight = min(4.0, math.log2(1 + hours) / 2)
    if minutes_2weeks:
        weight += 0.5
    return weight


def format_number(value):
    """9.0 -> "9", 9.5 -> "9,5" (десяткова кома для українського інтерфейсу)."""
    text = f"{value:.1f}"
    if text.endswith(".0"):
        text = text[:-2]
    return text.replace(".", ",")


def _join_names(names, limit=2):
    names = list(names)
    shown = [f"«{name}»" for name in names[:limit]]
    text = " та ".join(shown)
    if len(names) > limit:
        text += f" і ще {len(names) - limit}"
    return text


def build_recommendations(user, limit=None):
    games = {game.id: game for game in Game.objects.all()}
    game_by_appid = {g.steam_appid: g.id for g in games.values() if g.steam_appid}

    genres_by_game = {}
    for game_id, genre_id in GameGenre.objects.values_list("game_id", "genre_id"):
        genres_by_game.setdefault(game_id, set()).add(genre_id)

    # --- Сигнали користувача ---------------------------------------------------
    signals = {}  # game_id -> вага
    library_ids = set()

    for game_id, status in LibraryEntry.objects.filter(user=user).values_list("game_id", "status"):
        library_ids.add(game_id)
        signals[game_id] = signals.get(game_id, 0) + STATUS_WEIGHTS.get(status, 0)

    for game_id, score in Review.objects.filter(user=user).values_list("game_id", "score"):
        signals[game_id] = signals.get(game_id, 0) + review_weight(score)

    owned_on_steam = set()
    steam_items = (
        ExternalLibraryItem.objects
        .filter(user=user, provider="steam", external_game_id__in=game_by_appid.keys())
        .values_list("external_game_id", "playtime_minutes", "playtime_2weeks_minutes")
    )
    for appid, minutes, minutes_2weeks in steam_items:
        game_id = game_by_appid[appid]
        owned_on_steam.add(game_id)
        signals[game_id] = signals.get(game_id, 0) + steam_weight(minutes, minutes_2weeks)

    # Steam-ігри поза каталогом, у які користувач грав: жанри зі Steam Store.
    external_games = []  # (назва, сигнал, id жанрів каталогу)
    outside = list(
        ExternalLibraryItem.objects
        .filter(user=user, provider="steam", playtime_minutes__gt=0)
        .exclude(external_game_id__in=game_by_appid.keys())
        .values_list("external_game_id", "game_title", "playtime_minutes", "playtime_2weeks_minutes")
    )
    if outside:
        genre_index = catalog_genre_index()
        app_genres = dict(
            SteamApp.objects
            .filter(appid__in=[row[0] for row in outside], found=True)
            .values_list("appid", "genres")
        )
        for appid, title, minutes, minutes_2weeks in outside:
            genre_ids = map_steam_genres(app_genres.get(appid, "").split(","), genre_index)
            if genre_ids:
                external_games.append((title, STEAM_ONLY_FACTOR * steam_weight(minutes, minutes_2weeks), genre_ids))

    # --- Профіль жанрів ---------------------------------------------------------
    genre_weights = {}
    for game_id, signal in signals.items():
        for genre_id in genres_by_game.get(game_id, ()):
            genre_weights[genre_id] = genre_weights.get(genre_id, 0) + signal

    for _, signal, genre_ids in external_games:
        for genre_id in genre_ids:
            genre_weights[genre_id] = genre_weights.get(genre_id, 0) + signal

    max_abs = max((abs(w) for w in genre_weights.values()), default=0)
    affinity = {g: w / max_abs for g, w in genre_weights.items()} if max_abs else {}

    # Ігри, що найбільше сподобались, — для пояснень "схожа на ...":
    # (назва, сигнал, жанри, чи це Steam-гра поза каталогом).
    liked = [
        (games[gid].title, signal, genres_by_game[gid], False)
        for gid, signal in signals.items()
        if signal > 0 and genres_by_game.get(gid)
    ]
    liked += [(title, signal, genre_ids, True) for title, signal, genre_ids in external_games if signal > 0]
    liked.sort(key=lambda entry: (-entry[1], entry[0]))

    # --- Дані друзів ------------------------------------------------------------
    friend_ids = get_friend_ids(user)
    friend_names = dict(User.objects.filter(id__in=friend_ids).values_list("id", "username"))

    friend_owners = {}  # game_id -> set(friend_id)
    for friend_id, game_id in LibraryEntry.objects.filter(user_id__in=friend_ids).values_list("user_id", "game_id"):
        friend_owners.setdefault(game_id, set()).add(friend_id)

    friend_hours = {}
    friend_steam = (
        ExternalLibraryItem.objects
        .filter(user_id__in=friend_ids, provider="steam", external_game_id__in=game_by_appid.keys())
        .values_list("user_id", "external_game_id", "playtime_minutes")
    )
    for friend_id, appid, minutes in friend_steam:
        game_id = game_by_appid[appid]
        friend_owners.setdefault(game_id, set()).add(friend_id)
        friend_hours[game_id] = friend_hours.get(game_id, 0) + (minutes or 0) / 60

    friend_scores = {}
    for game_id, score in Review.objects.filter(user_id__in=friend_ids).values_list("game_id", "score"):
        friend_scores.setdefault(game_id, []).append(score)

    # --- Рейтинги каталогу -------------------------------------------------------
    rating_rows = Review.objects.values("game_id").annotate(avg=models.Avg("score"), n=models.Count("id"))
    ratings = {row["game_id"]: (float(row["avg"]), row["n"]) for row in rating_rows}

    popularity = dict(
        LibraryEntry.objects.values("game_id").annotate(n=models.Count("id")).values_list("game_id", "n")
    )

    dismissed = set(DismissedRecommendation.objects.filter(user=user).values_list("game_id", flat=True))
    excluded = library_ids | owned_on_steam | dismissed

    def quality(game_id):
        avg, n = ratings.get(game_id, (None, 0))
        if not n:
            return 0, None
        smoothed = (RATING_PRIOR_COUNT * PRIOR_RATING + avg * n) / (RATING_PRIOR_COUNT + n)
        points = round(QUALITY_POINTS * min(1.0, max(0.0, (smoothed - 5) / 5)))
        reason = None
        if smoothed >= 7:
            word = "відгук" if n == 1 else ("відгуки" if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14 else "відгуків")
            reason = f"Середня оцінка {format_number(avg)} ({n} {word})"
        return points, reason

    is_fallback = not signals and not external_games and not friend_owners
    results = []

    for game_id, game in games.items():
        if game_id in excluded:
            continue

        reasons = []

        # Жанри
        game_genres = genres_by_game.get(game_id, set())
        genre_points = 0
        if affinity and game_genres:
            values = [affinity.get(g, 0.0) for g in game_genres]
            match = 0.6 * max(values) + 0.4 * (sum(values) / len(values))
            genre_points = round(GENRE_POINTS * max(-1.0, min(1.0, match)))
            if genre_points > 0:
                similar = [entry for entry in liked if entry[2] & game_genres]
                if similar:
                    from_steam = {entry[3] for entry in similar}
                    source = (
                        "з вашого Steam" if from_steam == {True}
                        else "з вашої бібліотеки" if from_steam == {False}
                        else "з ваших ігор"
                    )
                    reasons.append(f"Схожа на {_join_names(e[0] for e in similar)} {source}")

        # Друзі
        owners = friend_owners.get(game_id, set())
        friend_points = 0.0
        if owners:
            friend_points = 20 * (1 - 0.5 ** len(owners))
            names = sorted(friend_names.get(fid, "") for fid in owners)
            reasons.append("Є у " + ", ".join(names[:3]) + (f" і ще {len(names) - 3}" if len(names) > 3 else ""))

            hours = friend_hours.get(game_id, 0)
            if hours >= 10:
                friend_points += 3
                reasons.append(f"Друзі награли {round(hours)} год у Steam")

        scores = friend_scores.get(game_id)
        if scores:
            friend_avg = sum(scores) / len(scores)
            if friend_avg >= 8:
                friend_points += 7
                reasons.append(f"Друзі оцінили в середньому {format_number(friend_avg)}/10")
            elif friend_avg <= 4:
                friend_points -= 7
        friend_points = round(max(-10.0, min(float(FRIEND_POINTS), friend_points)))

        # Якість
        quality_points, quality_reason = quality(game_id)
        if quality_reason:
            reasons.append(quality_reason)

        if is_fallback:
            # Немає даних про смаки: найкращі та найпопулярніші ігри каталогу.
            library_count = popularity.get(game_id, 0)
            score = quality_points * 3 + min(40, library_count * 10)
            if library_count:
                reasons.append(f"Популярна в GameVault: у {library_count} бібліотеках")
        else:
            score = genre_points + friend_points + quality_points

        score = max(0, min(100, score))
        if score < MIN_SCORE or not reasons:
            continue

        results.append(GameRecommendation(
            game=game,
            score=score,
            reasons=reasons,
            genre_points=max(0, genre_points),
            friend_points=max(0, friend_points),
            quality_points=quality_points,
        ))

    results.sort(key=lambda r: (-r.score, r.game.title))
    if limit is not None:
        results = results[:limit]

    return RecommendationResult(
        recommendations=results,
        is_fallback=is_fallback,
        has_steam_signals=bool(owned_on_steam or external_games),
    )
