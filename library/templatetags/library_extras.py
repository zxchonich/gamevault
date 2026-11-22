from django import template

from library.selectors import get_status_label

register = template.Library()


@register.filter
def status_label(status):
    """{{ entry.status|status_label }} -> "Пройдено" (про себе: "Планую", "Граю")."""
    return get_status_label(status)


@register.filter
def status_label_other(status):
    """Про іншого користувача: "Планує", "Грає"."""
    return get_status_label(status, other=True)
