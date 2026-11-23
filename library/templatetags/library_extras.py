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
