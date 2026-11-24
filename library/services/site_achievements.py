"""Власні досягнення GameVault: значки за дії на сайті (окремо від досягнень Steam).

Визначення — у ACHIEVEMENTS (ключ, назва, категорія, іконка, пороги рівнів). Прогрес рахується на льоту
(compute_metrics — кілька агрегатних запитів, лише для ще не завершених досягнень); у БД зберігаються
тільки отримані рівні (UserSiteAchievement) з датою.

check(user) викликається після дій, що можуть дати значок (activity.record_*), а також при відкритті
свого профілю й сторінки досягнень. Перший підрахунок користувача (users.achievements_synced_at IS NULL)
тихий — значки за минулі дії видаються без сповіщень і подій у стрічці. Далі за кожне досягнення, що
піднялося, — сповіщення власнику й подія в стрічці (одна, з найвищим новим рівнем).
"""

import datetime
from dataclasses import dataclass, field

from django.db.models import Count, Exists, F, Max, OuterRef, Sum
from django.db.models.functions import Length
from django.utils import timezone

from library.access import friend_ids
from library.models import (
    ActivityEvent,
    ExternalAccount,
    ExternalLibraryItem,
    GameGenre,
    GameRequest,
    LibraryEntry,
    Notification,
    PlaySession,
    Review,
    SteamAchievement,
    User,
    UserAchievement,
    UserSiteAchievement,
)

TIER_NAMES = {1: "бронза", 2: "срібло", 3: "золото"}
TIER_GENITIVE = {1: "бронзи", 2: "срібла", 3: "золота"}  # «7/10 до срібла»
SHOWCASE_SIZE = 5  # базовий розмір; більше — за місця з магазину (showcase_size)
RARE_STEAM_PERCENT = 5

CATEGORIES = [
    ("library", "Бібліотека"),
    ("reviews", "Рецензії"),
    ("community", "Друзі та спільнота"),
    ("steam", "Steam"),
]


@dataclass(frozen=True)
class Achievement:
    key: str
    title: str
    category: str
    icon: str
    thresholds: tuple   # пороги рівнів: (10, 50, 100) або (1,) для одноразового
    description: str    # «{n}» — поріг рівня
    unit: str = ""      # підпис прогресу: «7/10 {unit}»
    secret: bool = False

    @property
    def single(self):
        return len(self.thresholds) == 1

    @property
    def max_tier(self):
        return len(self.thresholds)

    def tier_for(self, value):
        return sum(1 for threshold in self.thresholds if value >= threshold)

    def describe(self, tier):
        threshold = self.thresholds[min(max(tier, 1), self.max_tier) - 1]
        return self.description.format(n=threshold)


ACHIEVEMENTS = [
    # Бібліотека
    Achievement("collector", "Колекціонер", "library", "box", (10, 50, 100), "Мати в бібліотеці {n} ігор", "ігор"),
    Achievement("finisher", "Фінішер", "library", "flag", (1, 10, 50), "Пройти ігор: {n}", "пройдено"),
    Achievement("omnivore", "Всеїдний", "library", "shapes", (3, 6, 10),
                "Пройти ігри {n} різних жанрів", "жанрів"),
    Achievement("no_dropped", "Без хвостів", "library", "shield", (20,),
                "Мати {n} ігор у бібліотеці й жодної закинутої", "ігор без закинутих", secret=True),
    # Рецензії
    Achievement("critic", "Критик", "reviews", "pen", (1, 10, 50), "Написати рецензій: {n}", "рецензій"),
    Achievement("writer", "Літератор", "reviews", "scroll", (500,),
                "Написати рецензію від {n} символів", "символів"),
    Achievement("fair_judge", "Суворий, але чесний", "reviews", "scale", (2,),
                "Поставити і низьку (1–3), і високу (9–10) оцінку", "", secret=True),
    # Друзі та спільнота
    Achievement("soul", "Душа компанії", "community", "users", (1, 5, 15), "Мати друзів: {n}", "друзів"),
    Achievement("pioneer", "Першовідкривач", "community", "compass", (1, 5, 15),
                "Схвалених заявок на ігри: {n}", "заявок"),
    Achievement("oldtimer", "Старожил", "community", "calendar", (30, 180, 365),
                "Бути на GameVault {n} днів", "днів"),
    # Steam
    Achievement("connected", "На зв'язку", "steam", "steam", (1,), "Прив'язати акаунт Steam"),
    Achievement("veteran", "Ветеран", "steam", "clock", (100, 1000, 5000), "Награти в Steam {n} годин", "годин"),
    Achievement("marathon", "Марафонець", "steam", "timer", (3, 6, 10),
                "Грати без перерви {n} годин", "год найдовша сесія"),
    Achievement("night_owl", "Нічна сова", "steam", "moon", (1,), "Грати о 3-й ночі", secret=True),
    Achievement("streak", "Без вихідних", "steam", "flame", (3, 7, 30),
                "Грати {n} днів поспіль", "днів поспіль"),
    Achievement("hunter", "Мисливець", "steam", "trophy", (50, 500, 2000),
                "Отримати досягнень Steam: {n}", "досягнень"),
    Achievement("rare_find", "Рідкісна знахідка", "steam", "gem", (1, 10, 50),
                f"Отримати досягнень Steam, які мають менше {RARE_STEAM_PERCENT}% гравців: {{n}}", "рідкісних"),
    Achievement("perfectionist", "Перфекціоніст", "steam", "star", (1, 5, 15),
                "Зібрати 100% досягнень Steam в іграх: {n}", "ігор"),
]
BY_KEY = {a.key: a for a in ACHIEVEMENTS}


# --- Метрики ---------------------------------------------------------------------------

def _sessions(user):
    return list(PlaySession.objects.filter(user=user).values_list("started_at", "last_seen_at"))


def _played_at_night(sessions):
    """Чи була сесія, що захоплює 3:00–4:00 за місцевим часом."""
    for start, end in sessions:
        start, end = timezone.localtime(start), timezone.localtime(end)
        if end - start >= datetime.timedelta(days=1) or start.hour == 3:
            return True
        three = start.replace(hour=3, minute=0, second=0, microsecond=0)
        if three < start:
            three += datetime.timedelta(days=1)
        if three <= end:
            return True
    return False


def _longest_streak(sessions):
    days = set()
    for start, end in sessions:
        day, last = timezone.localdate(start), timezone.localdate(end)
        while day <= last:
            days.add(day)
            day += datetime.timedelta(days=1)
    best = 0
    for day in days:
        if day - datetime.timedelta(days=1) in days:
            continue  # не початок серії
        length = 1
        while day + datetime.timedelta(days=length) in days:
            length += 1
        best = max(best, length)
    return best


def compute_metrics(user, keys=None):
    """{ключ: значення прогресу} для досягнень keys (за замовчуванням — усіх)."""
    keys = set(keys if keys is not None else BY_KEY)
    m = {}
    entries = LibraryEntry.objects.filter(user=user)

    if keys & {"collector", "no_dropped"}:
        counts = dict(entries.values("status").annotate(n=Count("id")).values_list("status", "n"))
        total = sum(counts.values())
        m["collector"] = total
        m["no_dropped"] = 0 if counts.get("dropped") else total
    if "finisher" in keys:
        m["finisher"] = entries.filter(status="completed").count()
    if "omnivore" in keys:
        m["omnivore"] = (
            GameGenre.objects.filter(game__library_entries__user=user, game__library_entries__status="completed")
            .values("genre_id").distinct().count()
        )

    reviews = Review.objects.filter(user=user)
    if "critic" in keys:
        m["critic"] = reviews.count()
    if "writer" in keys:
        m["writer"] = reviews.aggregate(n=Max(Length("text")))["n"] or 0
    if "fair_judge" in keys:
        m["fair_judge"] = int(reviews.filter(score__lte=3).exists()) + int(reviews.filter(score__gte=9).exists())

    if "soul" in keys:
        m["soul"] = len(friend_ids(user))
    if "pioneer" in keys:
        m["pioneer"] = GameRequest.objects.filter(user=user, status="approved").count()
    if "oldtimer" in keys:
        m["oldtimer"] = (timezone.now() - user.created_at).days if user.created_at else 0

    if "connected" in keys:
        m["connected"] = int(ExternalAccount.objects.filter(user=user, provider="steam").exists())
    if "veteran" in keys:
        minutes = ExternalLibraryItem.objects.filter(user=user, provider="steam").aggregate(n=Sum("playtime_minutes"))["n"]
        m["veteran"] = (minutes or 0) // 60
    if keys & {"marathon", "night_owl", "streak"}:
        sessions = _sessions(user)
        longest = max((end - start for start, end in sessions), default=datetime.timedelta())
        m["marathon"] = round(longest.total_seconds() / 3600, 1)
        m["night_owl"] = int(_played_at_night(sessions)) if "night_owl" in keys else 0
        m["streak"] = _longest_streak(sessions) if "streak" in keys else 0
    if "hunter" in keys:
        m["hunter"] = UserAchievement.objects.filter(user=user).count()
    if "rare_find" in keys:
        rare = SteamAchievement.objects.filter(
            appid=OuterRef("appid"), apiname=OuterRef("apiname"), percent__lt=RARE_STEAM_PERCENT
        )
        m["rare_find"] = UserAchievement.objects.filter(user=user).filter(Exists(rare)).count()
    if "perfectionist" in keys:
        m["perfectionist"] = ExternalLibraryItem.objects.filter(
            user=user, provider="steam", achievements_total__gt=0, achievements_unlocked=F("achievements_total")
        ).count()
    return {key: m.get(key, 0) for key in keys}


# --- Видача ----------------------------------------------------------------------------

def unlocked_tiers(user):
    """{ключ: найвищий отриманий рівень}."""
    rows = UserSiteAchievement.objects.filter(user=user).values("achievement_key").annotate(tier=Max("tier"))
    return {row["achievement_key"]: row["tier"] for row in rows}


def check(user, now=None):
    """Перераховує досягнення й видає нові рівні. Повертає [(Achievement, рівень)] нових."""
    now = now or timezone.now()
    current = unlocked_tiers(user)
    pending = [a.key for a in ACHIEVEMENTS if current.get(a.key, 0) < a.max_tier]
    silent = user.achievements_synced_at is None

    new = []
    if pending:
        metrics = compute_metrics(user, pending)
        for key in pending:
            achievement = BY_KEY[key]
            for tier in range(current.get(key, 0) + 1, achievement.tier_for(metrics[key]) + 1):
                new.append((achievement, tier))

    if new:
        UserSiteAchievement.objects.bulk_create(
            [UserSiteAchievement(user=user, achievement_key=a.key, tier=t, unlocked_at=now) for a, t in new],
            ignore_conflicts=True,
        )
        if not silent:
            top = {}
            for achievement, tier in new:
                top[achievement.key] = max(tier, top.get(achievement.key, 0))
            for key, tier in top.items():
                ActivityEvent.objects.create(
                    user=user, event_type=ActivityEvent.SITE_ACHIEVEMENT, achievement_key=key,
                    item_count=tier, created_at=now,
                )
                Notification.objects.create(
                    user=user, kind=Notification.SITE_ACHIEVEMENT, achievement_key=key, tier=tier, created_at=now,
                )
    if silent:
        User.objects.filter(id=user.id).update(achievements_synced_at=now)
        user.achievements_synced_at = now
    # Волти за рівні (і за отримані раніше, якщо ще не нараховано) — навіть коли перший підрахунок тихий.
    from . import volts
    volts.sync_site_rewards(user, now=now)
    return new


def check_quietly(user):
    """Для викликів після дій: досягнення не повинні ламати основну дію (вимикається SITE_ACHIEVEMENTS)."""
    import logging

    from django.conf import settings

    if not settings.SITE_ACHIEVEMENTS or user is None:
        return []
    try:
        return check(user)
    except Exception:  # noqa: BLE001 — значок не вартий помилки 500
        logging.getLogger(__name__).exception("Досягнення GameVault: помилка перевірки для %s", user.id)
        return []


# --- Показ -----------------------------------------------------------------------------

@dataclass
class TierView:
    tier: int
    name: str
    threshold: object
    unlocked_at: object = None
    rarity: object = None  # % користувачів сайту з цим рівнем


@dataclass
class AchievementView:
    achievement: Achievement
    tier: int                     # найвищий отриманий (0 — немає)
    value: object                 # поточний прогрес
    tiers: list = field(default_factory=list)
    hidden: bool = False          # секретне й ще не отримане

    @property
    def key(self):
        return self.achievement.key

    @property
    def unlocked(self):
        return self.tier > 0

    @property
    def done(self):
        return self.tier >= self.achievement.max_tier

    @property
    def next_threshold(self):
        return None if self.done else self.achievement.thresholds[self.tier]

    @property
    def percent(self):
        if self.done:
            return 100
        target = self.next_threshold
        return min(100, round(float(self.value) * 100 / target)) if target else 0

    @property
    def description(self):
        return self.achievement.describe(self.tier if self.done else self.tier + 1)

    @property
    def tier_name(self):
        return "" if self.achievement.single else TIER_NAMES.get(self.tier, "")

    @property
    def next_tier_name(self):
        return "" if self.achievement.single or self.done else TIER_GENITIVE[self.tier + 1]

    @property
    def unlocked_at(self):
        dates = [t.unlocked_at for t in self.tiers if t.unlocked_at]
        return max(dates) if dates else None

    @property
    def rarity(self):
        if not self.unlocked:
            return None
        return self.tiers[self.tier - 1].rarity

    @property
    def value_label(self):
        value = self.value
        return f"{value:g}" if isinstance(value, float) else str(value)


def rarity_map():
    """{(ключ, рівень): % користувачів}."""
    total = User.objects.count() or 1
    rows = UserSiteAchievement.objects.values("achievement_key", "tier").annotate(n=Count("user_id", distinct=True))
    return {(r["achievement_key"], r["tier"]): round(r["n"] * 100 / total) for r in rows}


def build_views(user, rarities=None):
    """Усі досягнення користувача з прогресом, датами й рідкістю (для сторінки й вітрини)."""
    rarities = rarity_map() if rarities is None else rarities
    dates = {
        (row.achievement_key, row.tier): row.unlocked_at
        for row in UserSiteAchievement.objects.filter(user=user)
    }
    current = {}
    for key, tier in dates:
        current[key] = max(tier, current.get(key, 0))
    pending = [a.key for a in ACHIEVEMENTS if current.get(a.key, 0) < a.max_tier]
    metrics = compute_metrics(user, pending)

    views = []
    for achievement in ACHIEVEMENTS:
        tier = current.get(achievement.key, 0)
        views.append(AchievementView(
            achievement=achievement,
            tier=tier,
            value=metrics.get(achievement.key, achievement.thresholds[-1]),
            tiers=[
                TierView(
                    tier=index,
                    name="" if achievement.single else TIER_NAMES[index],
                    threshold=threshold,
                    unlocked_at=dates.get((achievement.key, index)),
                    rarity=rarities.get((achievement.key, index), 0),
                )
                for index, threshold in enumerate(achievement.thresholds, 1)
            ],
            hidden=achievement.secret and tier == 0,
        ))
    return views


def group_by_category(views):
    return [(title, [v for v in views if v.achievement.category == key]) for key, title in CATEGORIES]


def summary(views):
    return {
        "unlocked": sum(1 for v in views if v.unlocked),
        "total": len(views),
        "tiers": sum(v.tier for v in views),
        "tiers_total": sum(v.achievement.max_tier for v in views),
    }


def showcase_keys(user):
    return [k for k in (user.achievement_showcase or "").split(",") if k in BY_KEY]


def showcase_size(user):
    """5 місць + куплені в магазині (shop.showcase_size)."""
    from .shop import showcase_size as size_for
    return size_for(user)


def showcase(user, views, size=None):
    """Значки для вітрини: вибрані користувачем або автоматично (найвищі рівні, найрідкісніші, нові)."""
    size = size or showcase_size(user)
    unlocked = {v.key: v for v in views if v.unlocked}
    chosen = [unlocked[k] for k in showcase_keys(user) if k in unlocked]
    if user.achievement_showcase is not None and chosen:
        return chosen[:size]
    ranked = sorted(
        unlocked.values(),
        key=lambda v: (-v.tier, v.rarity if v.rarity is not None else 100,
                       -(v.unlocked_at.timestamp() if v.unlocked_at else 0)),
    )
    return ranked[:size]


def save_showcase(user, keys):
    """Зберігає вибір вітрини (лише отримані, без повторів, до showcase_size). keys=None — автоматично."""
    if keys is None:
        user.achievement_showcase = None
    else:
        unlocked = set(unlocked_tiers(user))
        clean = list(dict.fromkeys(k for k in keys if k in unlocked))[:showcase_size(user)]
        user.achievement_showcase = ",".join(clean) if clean else None
    User.objects.filter(id=user.id).update(achievement_showcase=user.achievement_showcase)
    return user.achievement_showcase
