"""Стилі значків досягнень GameVault: жетон, емблема, картридж, щит.

Значок малюється як inline SVG. Форма залежить від стилю, кольори — від CSS-змінних рівня
(`--badge-t1..3-*`, `--badge-single-*` у gv.css), тож обидві теми працюють без змін тут.
Стиль обирає власник значків (`users.badge_style`, NULL — DEFAULT_STYLE); показується він скрізь,
де видно його значки: вітрина, сторінка досягнень, його події в стрічці, його сповіщення.
"""

DEFAULT_STYLE = "emblem"

STYLES = {
    "emblem": "Емблема",
    "hex": "Жетон",
    "cartridge": "Картридж",
    "shield": "Щит",
}


def normalize(style):
    return style if style in STYLES else DEFAULT_STYLE


# --- Двоколірні іконки 24×24 ------------------------------------------------------------
# Контур — currentColor (stroke задано на <svg>), напівпрозора заливка — {F}.
_F = 'fill="currentColor" fill-opacity=".3"'
_SOLID = 'fill="currentColor" stroke="none"'

ICONS = {
    "box": f'<path d="M12 3 20 7.5 12 12 4 7.5Z" fill="currentColor" fill-opacity=".5" stroke="none"/>'
           f'<path d="M4 7.5 12 12v9l-8-4.5Z" {_F} stroke="none"/>'
           '<path d="M12 3 20 7.5v9L12 21l-8-4.5v-9ZM4 7.5 12 12l8-4.5M12 12v9"/>',
    "flag": f'<path d="M6 21V3.5" stroke-width="2.2"/><path d="M6 4h12l-2.5 4.5L18 13H6Z" {_F}/>',
    "shapes": f'<circle cx="7.5" cy="7.5" r="4" {_F}/><rect x="13" y="3.5" width="7.5" height="7.5" rx="1.5" {_F}/>'
              f'<path d="M7.5 13.5 12 21H3Z" {_F}/><path d="m16.75 13.5 3.75 3.75-3.75 3.75L13 17.25Z" {_F}/>',
    "shield": f'<path d="M12 3 4.5 6v6c0 4.5 3.2 7.8 7.5 9 4.3-1.2 7.5-4.5 7.5-9V6Z" {_F}/>'
              '<path d="m8.5 12 2.5 2.5 4.5-5" stroke-width="2.2"/>',
    "pen": f'<path d="M5 19l1.2-4.6L15.5 5a2.1 2.1 0 0 1 3 3l-9.4 9.3Z" {_F}/><path d="m13.5 7 3 3M5 19h6"/>',
    "scroll": f'<path d="M6 3h8l4 4v14H6Z" {_F}/><path d="M14 3v4h4M9 12h6M9 16h4"/>',
    "scale": f'<circle cx="12" cy="4.5" r="1.5" {_SOLID}/><path d="M12 6v14M8 20h8M4.5 7.5h15"/>'
             f'<path d="M2.5 13.5a2.5 2.5 0 0 0 5 0L5 7.5Z" {_F}/><path d="M16.5 13.5a2.5 2.5 0 0 0 5 0L19 7.5Z" {_F}/>',
    "users": f'<circle cx="9" cy="8" r="3.5" {_F}/><path d="M2.5 20c0-3.6 2.9-5.5 6.5-5.5s6.5 1.9 6.5 5.5Z" {_F}/>'
             '<path d="M15.5 4.8a3.5 3.5 0 0 1 0 6.4M17.5 14.7c2.4.6 4 2.3 4 5.3"/>',
    "compass": f'<circle cx="12" cy="12" r="9" fill="currentColor" fill-opacity=".18"/>'
               '<path d="m15.5 8.5-2 5-5 2 2-5Z" fill="currentColor"/>',
    "calendar": f'<rect x="3.5" y="5" width="17" height="15" rx="2.5" {_F}/><path d="M3.5 10h17M8 3v4M16 3v4"/>'
                f'<rect x="7.5" y="13" width="3.5" height="3.5" rx=".8" {_SOLID}/>',
    "steam": f'<circle cx="15.5" cy="8.5" r="4.5" {_F}/><circle cx="15.5" cy="8.5" r="1.6" {_SOLID}/>'
             f'<circle cx="8.5" cy="16" r="3" {_F}/><path d="m10.9 14.3 2.2-2.4M2.5 12.6l3.4 1.6"/>',
    "clock": f'<circle cx="12" cy="12" r="8.5" {_F} stroke-width="2"/><path d="M12 7.5V12l3 2" stroke-width="2.2"/>',
    "timer": f'<circle cx="12" cy="13.5" r="7.5" {_F}/><path d="M12 13.5v-4M10 3h4M12 3v3M18.3 6.7l1.5-1.5"/>',
    "moon": f'<path d="M19 14.5A7.5 7.5 0 1 1 9.5 5a6 6 0 0 0 9.5 9.5Z" fill="currentColor" fill-opacity=".35"/>'
            f'<path d="m17 3 .7 1.6 1.6.7-1.6.7-.7 1.6-.7-1.6-1.6-.7 1.6-.7Z" {_SOLID}/>',
    "flame": '<path d="M12 21c-4 0-6.5-2.7-6.5-6.3 0-3.7 3-5.7 3.8-9.7 2.6 1.6 3.3 3.8 3.2 5.5 1-.6 1.8-1.7 2-3 '
             f'2.3 2 3.9 4.5 3.9 7.2 0 3.6-2.5 6.3-6.4 6.3Z" {_F}/>'
             '<path d="M12 21c-1.7 0-2.8-1.1-2.8-2.7 0-1.8 1.6-2.7 2.3-4.3 1.6 1 3.3 2.4 3.3 4.3 0 1.6-1.1 2.7-2.8 2.7Z" '
             'fill="currentColor" fill-opacity=".7" stroke="none"/>',
    "trophy": f'<path d="M7 4h10v5a5 5 0 0 1-10 0Z" {_F}/>'
              '<path d="M7 6H4.5a2.5 2.5 0 0 0 2.6 4.1M17 6h2.5a2.5 2.5 0 0 1-2.6 4.1M12 14v3M8.5 20.5h7"/>'
              f'<path d="M9.5 17h5v3.5h-5Z" {_F}/>',
    "gem": f'<path d="M7 4h10l4 5-9 11L3 9Z" {_F}/><path d="M7 4h10l4 5H3Z" fill="currentColor" fill-opacity=".3" stroke="none"/>'
           '<path d="M3 9h18M9.5 4 8 9l4 11 4-11-1.5-5"/>',
    "star": '<path d="m12 3 2.7 5.6 6.1.8-4.5 4.2 1.1 6.1L12 16.8l-5.4 2.9 1.1-6.1-4.5-4.2 6.1-.8Z" '
            'fill="currentColor" fill-opacity=".35"/>',
}


def _icon(name, x, y, size, cls):
    body = ICONS.get(name, ICONS["star"])
    return (f'<svg class="{cls}" x="{x}" y="{y}" width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" '
            f'stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">{body}</svg>')


def _secret(x, y, size):
    return f'<text class="b-q" x="{x}" y="{y}" text-anchor="middle" font-size="{size}">?</text>'


_NUMERALS = {1: "I", 2: "II", 3: "III"}


def _star_path(cx, top, scale=1.0):
    s = scale
    return (f"M{cx} {top}l{1.6*s:.2f} {3.4*s:.2f} {3.7*s:.2f} {0.5*s:.2f}-{2.7*s:.2f} {2.6*s:.2f} "
            f"{0.7*s:.2f} {3.7*s:.2f}-{3.3*s:.2f}-{1.8*s:.2f}-{3.3*s:.2f} {1.8*s:.2f} {0.7*s:.2f}-{3.7*s:.2f}"
            f"-{2.7*s:.2f}-{2.6*s:.2f} {3.7*s:.2f}-{0.5*s:.2f}Z")


# --- Форми ------------------------------------------------------------------------------
# tier: 1–3; single — одноразове досягнення; locked — ще не отримано; compact — маленький розмір
# (без плашок, зірок і контактів, які на 30 px не читаються).

def _emblem(icon, tier, single, locked, hidden, compact):
    h = 72 if compact or locked else 82
    parts = []
    if locked:
        parts.append('<circle class="b-lock" cx="38" cy="36" r="31" stroke-width="4" stroke-dasharray="5 5"/>')
    else:
        parts += [
            '<circle class="b-coin" cx="38" cy="36" r="31" stroke-width="6"/>',
            '<path class="b-shine" d="M12 28A27 27 0 0 1 64 28" stroke-width="2" stroke-linecap="round"/>',
            '<circle class="b-inner" cx="38" cy="36" r="23" stroke-width="1.5"/>',
        ]
    parts.append(_secret(38, 46, 26) if hidden else _icon(icon, 21, 19, 34, "b-glow"))
    if not locked and not compact:
        if single:
            parts.append('<rect class="b-chip" x="27" y="62" width="22" height="17" rx="8.5" stroke-width="3"/>')
            parts.append(f'<path class="b-ink-star" d="{_star_path(38, 65.5, 0.85)}"/>')
        else:
            parts.append('<rect class="b-chip" x="23" y="62" width="30" height="17" rx="8.5" stroke-width="3"/>')
            parts.append(f'<text class="b-num" x="38" y="74.5" text-anchor="middle" font-size="9.5">{_NUMERALS[tier]}</text>')
    return f"0 0 76 {h}", parts


_HEX_OUTER = "M38 4 67.4 21v34L38 72 8.6 55V21Z"


def _hex(icon, tier, single, locked, hidden, compact):
    if locked:
        parts = [f'<path class="b-lock" d="{_HEX_OUTER}" stroke-width="4" stroke-linejoin="round" stroke-dasharray="6 5"/>']
    else:
        parts = [
            f'<path class="b-rim" d="{_HEX_OUTER}" stroke-width="4" stroke-linejoin="round"/>',
            '<path class="b-face" d="M38 10 62.2 24v28L38 66 13.8 52V24Z"/>',
            '<path class="b-gloss" d="M38 10 62.2 24v14H13.8V24Z"/>',
        ]
    parts.append(_secret(38, 48, 28) if hidden else _icon(icon, 19, 19, 38, "b-on"))
    return "0 0 76 76", parts


_CART_BODY = "M10 2H58L74 18V66A8 8 0 0 1 66 74H10A8 8 0 0 1 2 66V10A8 8 0 0 1 10 2Z"


def _cartridge(icon, tier, single, locked, hidden, compact):
    if locked:
        parts = [f'<path class="b-lock" d="{_CART_BODY}" stroke-width="2" stroke-dasharray="5 4"/>']
        parts.append(_secret(38, 48, 26) if hidden else _icon(icon, 22, 22, 32, "b-glow"))
        return "0 0 76 76", parts
    parts = [
        f'<path class="b-cart" d="{_CART_BODY}" stroke-width="2"/>',
        '<path class="b-label" d="M10 2H58L74 18V20H2V10A8 8 0 0 1 10 2Z"/>',
    ]
    if not compact:
        if single:
            parts.append(f'<path class="b-ink-star" d="{_star_path(14, 5.5, 0.75)}"/>')
        else:
            parts.append(f'<text class="b-num" x="9" y="15" font-size="9">{_NUMERALS[tier]}</text>')
        parts += [f'<rect class="b-pin" x="{x}" y="66" width="3" height="5" rx="1"/>' for x in (25, 32, 39, 46)]
    parts.append(_secret(38, 52, 26) if hidden else _icon(icon, 22, 26, 32, "b-glow"))
    return "0 0 76 76", parts


_SHIELD_OUTER = "M38 4 66 12V38C66 58 53 70 38 78 23 70 10 58 10 38V12Z"


def _shield(icon, tier, single, locked, hidden, compact):
    h = 81 if compact else 96
    if locked:
        parts = [f'<path class="b-lock" d="{_SHIELD_OUTER}" stroke-width="2.5" stroke-linejoin="round" stroke-dasharray="5 4"/>']
    else:
        parts = [
            f'<path class="b-rim" d="{_SHIELD_OUTER}" stroke-width="3" stroke-linejoin="round"/>',
            '<path class="b-face" d="M38 10 60 16.5V38C60 54 49.5 64 38 70.5 26.5 64 16 54 16 38V16.5Z"/>',
            '<path class="b-side" d="M38 10 16 16.5V38C16 54 26.5 64 38 70.5Z"/>',
        ]
    parts.append(_secret(38, 50, 26) if hidden else _icon(icon, 21, 21, 34, "b-on"))
    if not compact:
        if single:
            stars = [(38, not locked)]
        else:
            stars = [(x, not locked and i < tier) for i, x in enumerate((24, 38, 52))]
        for x, on in stars:
            cls = "b-star" if on else "b-star-empty"
            parts.append(f'<path class="{cls}" d="{_star_path(x, 82.5)}" stroke-width="1.4" stroke-linejoin="round"/>')
    return f"0 0 76 {h}", parts


_SHAPES = {"emblem": _emblem, "hex": _hex, "cartridge": _cartridge, "shield": _shield}


def render(style, icon, tier=1, single=False, locked=False, hidden=False, compact=False):
    """SVG-розмітка значка (без зовнішнього <span>)."""
    style = normalize(style)
    tier = min(max(int(tier or 1), 1), 3)
    view_box, parts = _SHAPES[style](icon, tier, single, locked, hidden, compact)
    return f'<svg viewBox="{view_box}" aria-hidden="true" focusable="false">{"".join(parts)}</svg>'


def choices():
    return [{"key": key, "label": label, "default": key == DEFAULT_STYLE} for key, label in STYLES.items()]


def save(user, style):
    """Зберігає стиль; невідомий або дефолтний — NULL (щоб зміна дефолту діяла на цього користувача)."""
    from ..models import User

    value = style if style in STYLES and style != DEFAULT_STYLE else None
    user.badge_style = value
    User.objects.filter(id=user.id).update(badge_style=value)
    return value

