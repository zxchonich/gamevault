"""Досягнення GameVault: сторінка досягнень і вибір значків для вітрини профілю."""

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from ..access import can_view_profile, connection_between, library_login_required, redirect_to_next
from ..models import Notification, User
from ..services import badge_styles, notifications, shop, site_achievements
from .social import private_profile_response


def _render(request, viewer, owner):
    views = site_achievements.build_views(owner)
    return render(request, "library/achievements.html", {
        "profile_user": owner,
        "is_own": viewer.id == owner.id,
        "categories": site_achievements.group_by_category(views),
        "summary": site_achievements.summary(views),
    })


@library_login_required
def my_achievements(request):
    user = request.library_user
    site_achievements.check_quietly(user)  # «Старожил» тощо — залежать від часу, не від дій
    notifications.mark_read(user, kinds=[Notification.SITE_ACHIEVEMENT])
    return _render(request, user, user)


@library_login_required
def user_achievements(request, user_id):
    viewer = request.library_user
    owner = get_object_or_404(User, id=user_id)
    if viewer.id == owner.id:
        return redirect("library:my_achievements")
    if not can_view_profile(viewer, owner):
        return private_profile_response(request, viewer, owner, connection_between(viewer, owner))
    return _render(request, viewer, owner)


@require_POST
@library_login_required
def save_showcase(request):
    user = request.library_user
    style = request.POST.get("badge_style")
    if style is not None:
        if shop.can_use_style(badge_styles.normalize(style), shop.owned_keys(user)):
            badge_styles.save(user, style)
        else:
            messages.error(request, "Цей стиль значків потрібно спершу придбати в магазині.")
    if request.POST.get("auto"):
        site_achievements.save_showcase(user, None)
        messages.success(request, "Вітрина досягнень — знову автоматична.")
    else:
        site_achievements.save_showcase(user, request.POST.getlist("keys"))
        messages.success(request, "Вітрину досягнень збережено.")
    return redirect_to_next(request, "library:profile")
