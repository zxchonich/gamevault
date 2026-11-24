"""Волти й магазин косметики: shop/, wallet/ і дії купити / подарувати / вдягнути."""

from django.contrib import messages
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from ..access import friend_ids, library_login_required, redirect_to_next
from ..models import Notification, User
from ..services import notifications, shop, volts

WALLET_PAGE_SIZE = 30


@library_login_required
def shop_page(request):
    user = request.library_user
    friends = list(User.objects.filter(id__in=friend_ids(user)).order_by("username"))
    notifications.mark_read(user, kinds=[Notification.GIFT])
    return render(request, "library/shop.html", {
        "sections": shop.build_sections(user, friends),
        "has_friends": bool(friends),
    })


@library_login_required
def wallet(request):
    user = request.library_user
    page_obj = Paginator(volts.history(user), WALLET_PAGE_SIZE).get_page(request.GET.get("page"))
    return render(request, "library/wallet.html", {
        "page_obj": page_obj,
        "earn_rules": volts.EARN_RULES,
        "reason_labels": volts.REASON_LABELS,
    })


def _done(request):
    return redirect_to_next(request, "library:shop")


@require_POST
@library_login_required
def buy_item(request, key):
    try:
        item = shop.buy(request.library_user, key)
    except shop.ShopError as error:
        messages.error(request, str(error))
    else:
        if item.kind in shop.EQUIP_FIELDS or item.kind == "badge_style":
            shop.equip(request.library_user, key)
            messages.success(request, f"«{item.title}» — ваше, і вже вдягнуто.")
        else:
            messages.success(request, f"«{item.title}» — ваше.")
    return _done(request)


@require_POST
@library_login_required
def gift_item(request, key):
    friend = get_object_or_404(User, id=request.POST.get("friend") or 0)
    try:
        item = shop.gift(request.library_user, friend, key, show_in_feed=bool(request.POST.get("show_in_feed")))
    except shop.ShopError as error:
        messages.error(request, str(error))
    else:
        messages.success(request, f"Ви подарували {friend.username} {shop.gift_label(item.key)}.")
    return _done(request)


@require_POST
@library_login_required
def equip_item(request, key):
    try:
        item = shop.equip(request.library_user, key)
    except shop.ShopError as error:
        messages.error(request, str(error))
    else:
        messages.success(request, f"«{item.title}» вдягнуто.")
    return _done(request)


@require_POST
@library_login_required
def unequip_item(request, kind):
    shop.unequip(request.library_user, kind)
    messages.success(request, "Знято." if kind != "badge_style" else "Повернено стиль значків за замовчуванням.")
    return _done(request)
