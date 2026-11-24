"""Волти — валюта GameVault. Лише заробляються (купити за гроші, вивести чи передати не можна),
витрачаються в магазині косметики (services/shop.py).

Журнал — volt_transactions: кожне нарахування має ref_key, унікальний для користувача, тож за ту саму
дію (рівень досягнення, сесію, рецензію, день) двічі не нараховується. Баланс users.volts змінюється
в тій самій транзакції, що й запис журналу.

Нарахування викликаються з місць, де відбувається дія: site_achievements.check (рівні досягнень,
зокрема ретроактивно), steam_presence.close_session (сесії), steam_achievements.check_session
(досягнення Steam, отримані під час сесії — старі не рахуються), views.library.add_review (рецензії),
middleware (щоденний візит і серія днів). Помилки нарахувань не ламають основну дію (quietly).
"""

import logging
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.db.models import F, Sum
from django.utils import timezone

from ..models import User, VoltTransaction

log = logging.getLogger(__name__)

SITE_TIER_REWARD = {1: 50, 2: 100, 3: 200}
SITE_SINGLE_REWARD = 150
STEAM_ACH_REWARD = 2
STEAM_RARE_REWARD = 10
STEAM_RARE_PERCENT = 10
STEAM_DAILY_CAP = 100
SESSION_MINUTES_PER_VOLT = 10
SESSION_DAILY_CAP = 30
REVIEW_REWARD = 15
REVIEW_MIN_CHARS = 100
REVIEW_DAILY_LIMIT = 3
DAILY_REWARD = 5
STREAK_DAYS = 7
STREAK_REWARD = 25

SITE_ACHIEVEMENT = "site_achievement"
STEAM_ACHIEVEMENT = "steam_achievement"
SESSION = "session"
REVIEW = "review"
DAILY = "daily"
STREAK = "streak"
PURCHASE = "purchase"
GIFT = "gift"

REASON_LABELS = {
    SITE_ACHIEVEMENT: "Досягнення GameVault",
    STEAM_ACHIEVEMENT: "Досягнення Steam",
    SESSION: "Ігрова сесія",
    REVIEW: "Рецензія",
    DAILY: "Щоденний візит",
    STREAK: f"{STREAK_DAYS} днів поспіль",
    PURCHASE: "Покупка",
    GIFT: "Подарунок",
}

# Для сторінки «Волти»: як заробляти.
EARN_RULES = [
    ("Рівень досягнення GameVault", f"бронза {SITE_TIER_REWARD[1]} · срібло {SITE_TIER_REWARD[2]} · "
                                     f"золото {SITE_TIER_REWARD[3]} · одноразове {SITE_SINGLE_REWARD}"),
    ("Досягнення Steam під час гри", f"{STEAM_ACH_REWARD}, рідкісне (<{STEAM_RARE_PERCENT}%) — {STEAM_RARE_REWARD} · "
                                      f"до {STEAM_DAILY_CAP} на день"),
    ("Ігрова сесія", f"1 за кожні {SESSION_MINUTES_PER_VOLT} хв · до {SESSION_DAILY_CAP} на день"),
    ("Рецензія з текстом", f"{REVIEW_REWARD} · від {REVIEW_MIN_CHARS} символів, раз на гру, до {REVIEW_DAILY_LIMIT} на день"),
    ("Перший візит за день", f"{DAILY_REWARD} · кожен {STREAK_DAYS}-й день поспіль ще +{STREAK_REWARD}"),
]


class NotEnoughVolts(Exception):
    pass


def day_start(now=None):
    """Початок поточної доби за київським часом (TIME_ZONE) — межа денних лімітів."""
    local = timezone.localtime(now or timezone.now())
    return local.replace(hour=0, minute=0, second=0, microsecond=0)


def _today(user_id, reason, now=None):
    return VoltTransaction.objects.filter(user_id=user_id, reason=reason, created_at__gte=day_start(now))


def earned_today(user_id, reason, now=None):
    return _today(user_id, reason, now).aggregate(total=Sum("amount"))["total"] or 0


def grant(user_id, amount, reason, ref_key, note="", now=None, daily_cap=None):
    """Нараховує волти один раз на ref_key. Повертає нараховану суму (0 — уже було або вичерпано ліміт)."""
    amount = int(amount)
    if amount <= 0:
        return 0
    now = now or timezone.now()
    with transaction.atomic():
        if daily_cap is not None:
            # Блокуємо рядок користувача, щоб паралельні нарахування не перевищили ліміт.
            list(User.objects.select_for_update().filter(id=user_id).values_list("id", flat=True))
            amount = min(amount, daily_cap - earned_today(user_id, reason, now))
            if amount <= 0:
                return 0
        try:
            with transaction.atomic():
                VoltTransaction.objects.create(
                    user_id=user_id, amount=amount, reason=reason, ref_key=ref_key[:120],
                    note=(note or "")[:255] or None, created_at=now,
                )
        except IntegrityError:
            return 0
        User.objects.filter(id=user_id).update(volts=F("volts") + amount)
    return amount


def spend(user_id, amount, reason, ref_key, note="", now=None):
    """Списує волти (викликати всередині transaction.atomic разом із видачею предмета).
    Умовний UPDATE не дає піти в мінус навіть за паралельних запитів."""
    if not User.objects.filter(id=user_id, volts__gte=amount).update(volts=F("volts") - amount):
        raise NotEnoughVolts
    VoltTransaction.objects.create(
        user_id=user_id, amount=-amount, reason=reason, ref_key=ref_key[:120],
        note=(note or "")[:255] or None, created_at=now or timezone.now(),
    )


def balance(user_id):
    return User.objects.filter(id=user_id).values_list("volts", flat=True).first() or 0


def quietly(func, *args, **kwargs):
    """Нарахування не повинні ламати основну дію."""
    try:
        return func(*args, **kwargs)
    except Exception:  # noqa: BLE001
        log.exception("Волти: помилка в %s", getattr(func, "__name__", func))
        return 0


# --- Нарахування за дії ------------------------------------------------------------------

def site_reward(achievement, tier):
    return SITE_SINGLE_REWARD if achievement.single else SITE_TIER_REWARD.get(tier, 0)


def sync_site_rewards(user, now=None):
    """Нараховує за всі отримані рівні досягнень GameVault, за які ще не нараховано (і ретроактивно)."""
    from ..models import UserSiteAchievement
    from .site_achievements import BY_KEY, TIER_NAMES

    rows = UserSiteAchievement.objects.filter(user=user).values_list("achievement_key", "tier")
    paid = set(
        VoltTransaction.objects.filter(user=user, reason=SITE_ACHIEVEMENT).values_list("ref_key", flat=True)
    )
    total = 0
    for key, tier in rows:
        achievement = BY_KEY.get(key)
        ref = f"site:{key}:{tier}"
        if achievement is None or ref in paid:
            continue
        note = achievement.title if achievement.single else f"{achievement.title} · {TIER_NAMES.get(tier, '')}"
        total += grant(user.id, site_reward(achievement, tier), SITE_ACHIEVEMENT, ref, note=note, now=now)
    return total


def session_reward(session):
    minutes = session.minutes or 0
    return grant(
        session.user_id, minutes // SESSION_MINUTES_PER_VOLT, SESSION, f"session:{session.id}",
        note=session.game_name or "", now=session.ended_at, daily_cap=SESSION_DAILY_CAP,
    )


def steam_achievement_rewards(user_id, appid, apinames, now=None):
    """За досягнення Steam, отримані під час сесії. apinames — нові досягнення цієї гри."""
    from ..models import SteamAchievement

    if not apinames:
        return 0
    schema = {
        a.apiname: a for a in SteamAchievement.objects.filter(appid=appid, apiname__in=list(apinames))
    }
    total = 0
    for apiname in apinames:
        info = schema.get(apiname)
        rare = info is not None and info.percent is not None and float(info.percent) < STEAM_RARE_PERCENT
        total += grant(
            user_id, STEAM_RARE_REWARD if rare else STEAM_ACH_REWARD, STEAM_ACHIEVEMENT,
            f"steam:{appid}:{apiname}", note=info.name if info else apiname, now=now, daily_cap=STEAM_DAILY_CAP,
        )
    return total


def review_reward(user, game, text, now=None):
    """Рецензія з текстом від REVIEW_MIN_CHARS символів — раз на гру, до REVIEW_DAILY_LIMIT на день."""
    if len((text or "").strip()) < REVIEW_MIN_CHARS:
        return 0
    if _today(user.id, REVIEW, now).count() >= REVIEW_DAILY_LIMIT:
        return 0
    return grant(user.id, REVIEW_REWARD, REVIEW, f"review:{game.id}", note=game.title, now=now)


def daily_visit(user_id, now=None):
    """Перший візит за день; кожен STREAK_DAYS-й день поспіль — бонус."""
    now = now or timezone.now()
    today = day_start(now).date()
    granted = grant(user_id, DAILY_REWARD, DAILY, f"daily:{today.isoformat()}", now=now)
    if not granted:
        return 0
    since = day_start(now) - timedelta(days=60)
    days = {
        ref.split(":", 1)[1]
        for ref in VoltTransaction.objects.filter(user_id=user_id, reason=DAILY, created_at__gte=since)
        .values_list("ref_key", flat=True)
    }
    streak = 0
    day = today
    while day.isoformat() in days:
        streak += 1
        day -= timedelta(days=1)
    if streak and streak % STREAK_DAYS == 0:
        granted += grant(user_id, STREAK_REWARD, STREAK, f"streak:{today.isoformat()}",
                         note=f"{streak} днів поспіль", now=now)
    return granted


def maybe_daily_visit(user_id):
    """З middleware: дешева перевірка через кеш, щоб не ходити в БД на кожному запиті."""
    from django.conf import settings
    from django.core.cache import cache

    if not getattr(settings, "VOLTS_DAILY", True):
        return 0
    key = f"volts:daily:{user_id}:{day_start().date().isoformat()}"
    if cache.get(key):
        return 0
    cache.set(key, True, 26 * 3600)
    return quietly(daily_visit, user_id)


def history(user):
    return VoltTransaction.objects.filter(user=user).order_by("-created_at", "-id")
