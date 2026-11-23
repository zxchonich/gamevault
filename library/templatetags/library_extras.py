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
