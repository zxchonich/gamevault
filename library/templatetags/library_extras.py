from django import template

from library.selectors import cover_colors, get_status_label

register = template.Library()


@register.filter
def status_label(status):
    """{{ entry.status|status_label }} -> "Пройдено" (про себе: "Планую", "Граю")."""
    return get_status_label(status)


@register.filter
def status_label_other(status):
    """Про іншого користувача: "Планує", "Грає"."""
    return get_status_label(status, other=True)


@register.simple_tag
def static_v(path):
    """{% static_v 'library/css/gv.css' %} — URL статики з ?v=<час зміни файлу>,
    щоб браузер не тримав стару закешовану версію після оновлення стилів."""
    import os

    from django.contrib.staticfiles import finders
    from django.templatetags.static import static

    url = static(path)
    found = finders.find(path)
    if found:
        url = f"{url}?v={int(os.path.getmtime(found))}"
    return url


# --- Іконки ---------------------------------------------------------------------
# Контурні іконки 24×24 (stroke = currentColor). Використання: {% icon "sync" %}.
ICONS = {
    "library": '<path d="M5 4h3v16H5zM10 4h3v16h-3z"/><path d="m15 5 3-.8 3.4 15-3 .8z"/>',
    "user": '<circle cx="12" cy="8" r="4"/><path d="M4 21c0-4 3.6-6 8-6s8 2 8 6"/>',
    "user-plus": '<circle cx="10" cy="8" r="4"/><path d="M2 21c0-4 3.6-6 8-6 1.4 0 2.7.2 3.8.6M19 14v6M16 17h6"/>',
    "user-minus": '<circle cx="10" cy="8" r="4"/><path d="M2 21c0-4 3.6-6 8-6 1.4 0 2.7.2 3.8.6M16 17h6"/>',
    "sync": '<path d="M20 11a8 8 0 0 0-14.3-4.9L4 8M4 13a8 8 0 0 0 14.3 4.9L20 16"/><path d="M4 3v5h5M20 21v-5h-5"/>',
    "unlink": '<path d="M9 7.5 10.5 6a4.2 4.2 0 0 1 6 6L15 13.5M15 16.5 13.5 18a4.2 4.2 0 0 1-6-6L9 10.5"/><path d="M4 4l3 3M20 20l-3-3"/>',
    "trash": '<path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/>',
    "play": '<path d="M8 5v14l11-7z" fill="currentColor"/>',
    "check": '<path d="m5 12.5 4.5 4.5L19 7.5"/>',
    "x": '<path d="M6 6l12 12M18 6 6 18"/>',
    "external": '<path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/>',
    "mail": '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3 7 9 6 9-6"/>',
    "key": '<circle cx="8" cy="15" r="4"/><path d="m10.8 12.2 8.7-8.7M17 6l3 3M14.5 8.5l2 2"/>',
    "steam": '<circle cx="15.5" cy="8.5" r="3.5"/><circle cx="15.5" cy="8.5" r="1" fill="currentColor"/><circle cx="8.5" cy="16" r="2.5"/><path d="m10.6 14.6 2.4-3.3M2.5 12.6l4 1.8"/>',
    "bell": '<path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10.3 21a1.9 1.9 0 0 0 3.4 0"/>',
    "box": '<path d="M3.5 7.5 12 3l8.5 4.5v9L12 21l-8.5-4.5z"/><path d="M3.5 7.5 12 12l8.5-4.5M12 12v9"/>',
    "flag": '<path d="M5 21V4M5 4h11l-2 4 2 4H5"/>',
    "shapes": '<circle cx="7" cy="7" r="3.5"/><rect x="13" y="3.5" width="7" height="7" rx="1"/><path d="m7 13.5 4 7H3zM16.5 13.5l3.5 3.5-3.5 3.5-3.5-3.5z"/>',
    "shield": '<path d="M12 3 4.5 6v6c0 4.5 3.2 7.8 7.5 9 4.3-1.2 7.5-4.5 7.5-9V6z"/><path d="m8.5 12 2.5 2.5 4.5-5"/>',
    "pen": '<path d="M4 20h4L19 9a2.8 2.8 0 0 0-4-4L4 16z"/><path d="m13.5 6.5 4 4"/>',
    "scroll": '<path d="M7 4h11a2 2 0 0 1 2 2v1h-4M7 4a2 2 0 0 0-2 2v12a2 2 0 0 1-2-2v-1h4"/><path d="M7 4v14a2 2 0 0 0 2 2h9a2 2 0 0 0 2-2V7M10 9h6M10 13h6"/>',
    "scale": '<path d="M12 4v16M8 20h8M5 7h14M12 4l-1 3h2z"/><path d="m5 7-3 6a3 3 0 0 0 6 0zM19 7l-3 6a3 3 0 0 0 6 0z"/>',
    "users": '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20c0-3.5 3-5.5 6.5-5.5s6.5 2 6.5 5.5"/><path d="M15.5 4.6a3.5 3.5 0 0 1 0 6.8M17.5 14.7c2.4.6 4 2.4 4 5.3"/>',
    "compass": '<circle cx="12" cy="12" r="9"/><path d="m15.5 8.5-2 5-5 2 2-5z"/>',
    "calendar": '<rect x="3.5" y="5" width="17" height="15.5" rx="2"/><path d="M3.5 10h17M8 3v4M16 3v4"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "timer": '<circle cx="12" cy="13.5" r="7.5"/><path d="M12 13.5V9.5M9.5 2.5h5M19 6.5l-1.5 1.5"/>',
    "moon": '<path d="M20 14.5A8.5 8.5 0 1 1 9.5 4a7 7 0 0 0 10.5 10.5z"/>',
    "flame": '<path d="M12 21c-4 0-7-2.7-7-6.5 0-4 3-6 4-10 2 1.5 3 3.5 3 5.5 1-1 1.5-2 1.5-3.5 2.5 2 4.5 4.8 4.5 8 0 3.8-2.6 6.5-6 6.5z"/>',
    "gem": '<path d="M6.5 3.5h11L21 9l-9 11.5L3 9z"/><path d="M3 9h18M12 20.5 8.5 9l3.5-5.5L15.5 9z"/>',
    "star": '<path d="m12 3 2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1-4.4-4.3 6.1-.9z"/>',
    "grip": '<circle cx="9" cy="6" r="1.2" fill="currentColor"/><circle cx="15" cy="6" r="1.2" fill="currentColor"/><circle cx="9" cy="12" r="1.2" fill="currentColor"/><circle cx="15" cy="12" r="1.2" fill="currentColor"/><circle cx="9" cy="18" r="1.2" fill="currentColor"/><circle cx="15" cy="18" r="1.2" fill="currentColor"/>',
    "edit": '<path d="M4 20h4L19 9a2.8 2.8 0 0 0-4-4L4 16z"/>',
    "ban": '<circle cx="12" cy="12" r="9"/><path d="m5.6 5.6 12.8 12.8"/>',
    "trophy": '<path d="M8 4h8v5a4 4 0 0 1-8 0zM8 6H5a3 3 0 0 0 3 4M16 6h3a3 3 0 0 1-3 4M12 13v4M8 20h8M10 17h4"/>',
    "gamepad": '<rect x="2.5" y="7" width="19" height="11" rx="5"/><path d="M7 11v3M5.5 12.5h3"/><circle cx="15.5" cy="11.5" r=".9" fill="currentColor"/><circle cx="17.5" cy="13.8" r=".9" fill="currentColor"/>',
    "settings": '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>',
}


@register.simple_tag
def icon(name, size=18):
    """{% icon "sync" %} — інлайн-SVG іконка (декоративна: підпис дає aria-label кнопки)."""
    from django.utils.safestring import mark_safe

    return mark_safe(
        f'<svg class="gv-icon" aria-hidden="true" width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" '
        f'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">{ICONS[name]}</svg>'
    )


# --- Компоненти нового дизайну --------------------------------------------------

AVATAR_COLORS = ["#7C5CFF", "#2F9E6E", "#E0533F", "#2A7FD4", "#C2418F", "#B7791F"]


@register.inclusion_tag("library/components/cover.html")
def game_cover(game, size=""):
    """{% game_cover game %} — постер гри або кольорова плашка з назвою."""
    bg, ink = cover_colors(game)
    return {"game": game, "size": size, "bg": bg, "ink": ink}


@register.inclusion_tag("library/components/avatar.html")
def user_avatar(user, size=""):
    """{% user_avatar user "sm" %} — фото або перша літера на кольоровому тлі."""
    return {
        "user": user,
        "size": size,
        "color": AVATAR_COLORS[(user.id or 0) % len(AVATAR_COLORS)],
    }


@register.simple_tag(takes_context=True)
def nav_active(context, *url_names):
    """class="{% nav_active 'my_library' 'user_library' %}" -> "is-active" на поточній сторінці."""
    request = context.get("request")
    match = getattr(request, "resolver_match", None)
    return "is-active" if match and match.url_name in url_names else ""


@register.simple_tag(takes_context=True)
def url_with(context, **params):
    """?поточні_параметри з заміною: href="{% url_with page=2 %}" (фільтри зберігаються)."""
    query = context["request"].GET.copy()
    for key, value in params.items():
        if value in ("", None):
            query.pop(key, None)  # порожнє значення прибирає параметр
        else:
            query[key] = value
    return "?" + query.urlencode()


@register.inclusion_tag("library/components/pagination.html", takes_context=True)
def pagination(context, page_obj):
    """{% pagination page_obj %} — номери сторінок навколо поточної, з першою й останньою."""
    current, last = page_obj.number, page_obj.paginator.num_pages
    pages = sorted({1, last, *range(max(1, current - 2), min(last, current + 2) + 1)})
    items, previous = [], 0
    for number in pages:
        if number - previous > 1:
            items.append(None)  # «…»
        items.append(number)
        previous = number
    return {"request": context["request"], "page_obj": page_obj, "items": items}


@register.filter
def cover_bg(game):
    return cover_colors(game)[0]


@register.filter
def cover_ink(game):
    return cover_colors(game)[1]


@register.inclusion_tag("library/components/score_ring.html")
def score_ring(score, size=64):
    """Відсоток збігу кільцем: {% score_ring recommendation.score 72 %}."""
    score = max(0, min(100, int(score or 0)))
    return {"score": score, "size": size}


MONTHS_GENITIVE = [
    "січня", "лютого", "березня", "квітня", "травня", "червня",
    "липня", "серпня", "вересня", "жовтня", "листопада", "грудня",
]


@register.filter
def day_label(value):
    """Дата події для розділювачів стрічки: «Сьогодні», «Вчора», «12 листопада» (+рік, якщо не поточний)."""
    import datetime

    from django.utils import timezone

    if not value:
        return ""
    day = timezone.localtime(value).date() if isinstance(value, datetime.datetime) else value
    today = timezone.localdate()
    if day == today:
        return "Сьогодні"
    if day == today - datetime.timedelta(days=1):
        return "Вчора"
    label = f"{day.day} {MONTHS_GENITIVE[day.month - 1]}"
    return label if day.year == today.year else f"{label} {day.year}"


@register.filter
def ago(value):
    """«щойно», «5 хв тому», «3 год тому», «вчора о 14:20», «12 листопада» — час сповіщення українською."""
    import datetime

    from django.utils import timezone

    if not value:
        return ""
    seconds = (timezone.now() - value).total_seconds()
    if seconds < 60:
        return "щойно"
    if seconds < 3600:
        return f"{int(seconds // 60)} хв тому"
    if seconds < 6 * 3600:
        return f"{int(seconds // 3600)} год тому"
    local = timezone.localtime(value)
    today = timezone.localdate()
    if local.date() == today:
        return f"сьогодні о {local:%H:%M}"
    if local.date() == today - datetime.timedelta(days=1):
        return f"вчора о {local:%H:%M}"
    return day_label(value)


@register.filter
def minutes_label(minutes):
    """45 -> «45 хв», 120 -> «2 год», 135 -> «2 год 15 хв» — тривалість ігрової сесії."""
    try:
        minutes = max(int(minutes or 0), 1)
    except (TypeError, ValueError):
        return ""
    hours, rest = divmod(minutes, 60)
    if not hours:
        return f"{rest} хв"
    return f"{hours} год {rest} хв" if rest else f"{hours} год"



@register.inclusion_tag("library/components/site_badge.html")
def site_badge(key, tier=0, size="", hidden=False, style=None):
    """{% site_badge "finisher" 2 "lg" style=profile_user.badge_style %} — значок досягнення GameVault.

    tier 0 — ще не отримано (сірий); hidden — секретне (знак питання замість іконки);
    style — стиль власника значка (services/badge_styles.py), None — за замовчуванням."""
    from django.utils.safestring import mark_safe

    from library.services import badge_styles
    from library.services.site_achievements import BY_KEY, TIER_NAMES

    achievement = BY_KEY.get(key)
    if achievement is None:
        return {"badge": None}
    style = badge_styles.normalize(style)
    locked = tier == 0
    svg = badge_styles.render(
        style, achievement.icon, tier=tier, single=achievement.single,
        locked=locked, hidden=hidden, compact=size == "sm",
    )
    return {
        "badge": achievement,
        "style": style,
        "tier_class": "single" if achievement.single else f"t{min(max(tier, 1), 3)}",
        "tier_name": "" if achievement.single else TIER_NAMES.get(tier, ""),
        "size": size,
        "locked": locked,
        "hidden": hidden,
        "svg": mark_safe(svg),
    }


@register.filter
def achievement_title(key):
    from library.services.site_achievements import BY_KEY

    achievement = BY_KEY.get(key)
    return achievement.title if achievement else key


@register.filter
def tier_label(tier, key):
    """{{ tier|tier_label:key }} — «срібло»; для одноразових досягнень — порожньо."""
    from library.services.site_achievements import BY_KEY, TIER_NAMES

    achievement = BY_KEY.get(key)
    if achievement is None or achievement.single:
        return ""
    return TIER_NAMES.get(tier, "")
