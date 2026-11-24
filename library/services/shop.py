"""Магазин косметики за волти: стилі значків, рамки аватара, титули, місця у вітрині.

Предмети описані тут (ITEMS), у БД — лише куплені/подаровані (`user_items`) і одягнені
(`users.avatar_frame`, `users.profile_title`, `users.badge_style`). Новий предмет — рядок у ITEMS
(для рамки — ще стиль `.gv-frame--<ключ>` у gv.css).

Покупка й подарунок — одна транзакція: умовне списання (volts.spend) + запис предмета; унікальні
ключі (`user_items`, ref_key журналу) не дають купити двічі навіть подвійним кліком.
"""

from dataclasses import dataclass

from django.db import IntegrityError, transaction
from django.utils import timezone

from ..models import ActivityEvent, Notification, User, UserItem
from . import badge_styles, volts

BASE_SHOWCASE_SIZE = 5


class ShopError(Exception):
    """Помилка з текстом для користувача."""


@dataclass(frozen=True)
class Item:
    key: str
    kind: str
    title: str
    price: int
    description: str = ""
    value: str = ""          # для стилю значків — ключ стилю з badge_styles.STYLES
    giftable: bool = True
    requires: str = ""       # спершу треба мати цей предмет (місця вітрини — по черзі)


KINDS = [
    ("badge_style", "Стилі значків", "Форма значків досягнень у вашому профілі, стрічці й сповіщеннях."),
    ("frame", "Рамки аватара", "Рамка навколо аватара — у профілі, стрічці, списках друзів."),
    ("title", "Титули", "Підпис під ніком у профілі та в картках друзів."),
    ("slot", "Вітрина", "Більше значків у вітрині профілю."),
]
KIND_LABELS = {key: label for key, label, _ in KINDS}
# Знахідний відмінок для «дарує вам …».
KIND_ACCUSATIVE = {"badge_style": "стиль значків", "frame": "рамку аватара", "title": "титул", "slot": "місце у вітрині"}

ITEMS = [
    Item("style_cartridge", "badge_style", "Картридж", 300, "Ігровий картридж: етикетка кольору рівня і контакти.", "cartridge"),
    Item("style_shield", "badge_style", "Щит", 300, "Щит кольору рівня, а рівень — зірками під ним.", "shield"),
    Item("frame_neon", "frame", "Неон", 200, "Світне кільце акцентного кольору."),
    Item("frame_pixel", "frame", "Піксель", 300, "Ступінчаста рамка в дусі 8-біт."),
    Item("frame_cartridge", "frame", "Картридж", 400, "Фіолетово-лаймова рамка в стилі сайту."),
    Item("frame_gold", "frame", "Золото", 500, "Золотий обідок для колекціонерів."),
    Item("title_night", "title", "Нічний гравець", 250),
    Item("title_collector", "title", "Колекціонер", 250),
    Item("title_critic", "title", "Критик", 250),
    Item("title_marathon", "title", "Марафонець", 250),
    Item("title_hunter", "title", "Мисливець за трофеями", 250),
    Item("slot_6", "slot", "6-те місце у вітрині", 400, "Ще один значок у вітрині профілю.", giftable=False),
    Item("slot_7", "slot", "7-ме місце у вітрині", 400, "Ще один значок у вітрині профілю.", giftable=False, requires="slot_6"),
    Item("slot_8", "slot", "8-ме місце у вітрині", 400, "Ще один значок у вітрині профілю.", giftable=False, requires="slot_7"),
]
BY_KEY = {item.key: item for item in ITEMS}
STYLE_ITEMS = {item.value: item for item in ITEMS if item.kind == "badge_style"}
FREE_STYLES = {style for style in badge_styles.STYLES if style not in STYLE_ITEMS}
EQUIP_FIELDS = {"frame": "avatar_frame", "title": "profile_title"}


def owned_keys(user):
    return set(UserItem.objects.filter(user=user).values_list("item_key", flat=True))


def showcase_size(user, owned=None):
    owned = owned_keys(user) if owned is None else owned
    return BASE_SHOWCASE_SIZE + sum(1 for key in owned if BY_KEY.get(key) and BY_KEY[key].kind == "slot")


def can_use_style(style, owned):
    return style in FREE_STYLES or (style in STYLE_ITEMS and STYLE_ITEMS[style].key in owned)


def _get(key):
    item = BY_KEY.get(key)
    if item is None:
        raise ShopError("Такого предмета немає.")
    return item


def buy(user, key):
    item = _get(key)
    try:
        with transaction.atomic():
            owned = owned_keys(user)
            if key in owned:
                raise ShopError("Цей предмет уже у вас.")
            if item.requires and item.requires not in owned:
                raise ShopError(f"Спершу придбайте «{BY_KEY[item.requires].title}».")
            volts.spend(user.id, item.price, volts.PURCHASE, f"buy:{key}", note=item.title)
            UserItem.objects.create(user=user, item_key=key, acquired_at=timezone.now())
    except volts.NotEnoughVolts:
        raise ShopError("Не вистачає волтів.") from None
    except IntegrityError:
        raise ShopError("Цей предмет уже у вас.") from None
    user.volts = volts.balance(user.id)
    return item


def gift(giver, friend, key, show_in_feed=True):
    from ..access import are_friends

    item = _get(key)
    if not item.giftable:
        raise ShopError("Цей предмет не можна подарувати.")
    if friend.id == giver.id or not are_friends(giver, friend):
        raise ShopError("Дарувати можна лише друзям.")
    now = timezone.now()
    try:
        with transaction.atomic():
            if UserItem.objects.filter(user=friend, item_key=key).exists():
                raise ShopError(f"У {friend.username} цей предмет уже є.")
            volts.spend(giver.id, item.price, volts.GIFT, f"gift:{key}:{friend.id}",
                        note=f"{item.title} → {friend.username}", now=now)
            UserItem.objects.create(user=friend, item_key=key, gifted_by=giver, acquired_at=now)
            Notification.objects.create(user=friend, kind=Notification.GIFT, actor=giver, item_key=key, created_at=now)
            if show_in_feed:
                ActivityEvent.objects.create(
                    user=giver, event_type=ActivityEvent.GIFT, target_user=friend, item_key=key, created_at=now,
                )
    except volts.NotEnoughVolts:
        raise ShopError("Не вистачає волтів.") from None
    except IntegrityError:
        raise ShopError(f"У {friend.username} цей предмет уже є.") from None
    giver.volts = volts.balance(giver.id)
    return item


def equip(user, key):
    """Вдягає предмет (рамку, титул, стиль значків)."""
    item = _get(key)
    if key not in owned_keys(user):
        raise ShopError("Спершу придбайте цей предмет.")
    if item.kind == "badge_style":
        badge_styles.save(user, item.value)
    elif item.kind in EQUIP_FIELDS:
        field = EQUIP_FIELDS[item.kind]
        setattr(user, field, key)
        User.objects.filter(id=user.id).update(**{field: key})
    else:
        raise ShopError("Цей предмет діє автоматично.")
    return item


def unequip(user, kind):
    if kind == "badge_style":
        badge_styles.save(user, None)
    elif kind in EQUIP_FIELDS:
        setattr(user, EQUIP_FIELDS[kind], None)
        User.objects.filter(id=user.id).update(**{EQUIP_FIELDS[kind]: None})


def equipped_key(user, kind):
    if kind == "badge_style":
        item = STYLE_ITEMS.get(badge_styles.normalize(user.badge_style))
        return item.key if item else None
    field = EQUIP_FIELDS.get(kind)
    return getattr(user, field) if field else None


def title_text(key):
    item = BY_KEY.get(key)
    return item.title if item and item.kind == "title" else ""


def gift_label(key):
    """«рамку аватара «Неон»» — для стрічки й сповіщень."""
    item = BY_KEY.get(key)
    if item is None:
        return "подарунок"
    return f"{KIND_ACCUSATIVE.get(item.kind, '')} «{item.title}»".strip()


@dataclass
class ItemView:
    item: Item
    owned: bool
    equipped: bool
    affordable: bool
    blocked_by: str = ""        # назва попереднього місця вітрини, якщо його ще немає
    gift_friends: list = None   # друзі, у яких предмета ще немає


def build_sections(user, friends=()):
    """Секції магазину для сторінки shop/. friends — список User для подарунків."""
    owned = owned_keys(user)
    friend_items = {}
    if friends:
        for user_id, key in UserItem.objects.filter(user__in=friends).values_list("user_id", "item_key"):
            friend_items.setdefault(key, set()).add(user_id)
    sections = []
    for kind, label, description in KINDS:
        equipped = equipped_key(user, kind)
        views = []
        for item in (i for i in ITEMS if i.kind == kind):
            blocked = item.requires and item.requires not in owned and item.key not in owned
            views.append(ItemView(
                item=item,
                owned=item.key in owned,
                equipped=item.key == equipped,
                affordable=user.volts >= item.price,
                blocked_by=BY_KEY[item.requires].title if blocked else "",
                gift_friends=[f for f in friends if f.id not in friend_items.get(item.key, set())] if item.giftable else [],
            ))
        sections.append({"kind": kind, "label": label, "description": description, "items": views})
    return sections
