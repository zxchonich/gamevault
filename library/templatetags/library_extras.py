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
