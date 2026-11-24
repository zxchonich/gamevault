"""Користувачі, друзі, профілі."""

from django.contrib import messages
from django.contrib.auth.hashers import make_password
from django.db import models
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from ..access import (
    block_state,
    blocked_by_ids,
    can_view_profile,
    connection_between,
    friend_ids,
    hidden_user_ids,
    library_login_required,
    redirect_to_next,
    update_session_after_password_change,
)
from ..forms import ProfileForm
from ..models import LibraryEntry, Notification, SocialConnection, User, UserBlock
from ..selectors import profile_backdrop, profile_stats
from ..storage import delete_unused_file
from ..services import activity, notifications, site_achievements, steam_achievements, steam_presence
from ..services.account_email import send_verification_email
from ..services.recommendations import top_genres
from ..services.social_auth import can_remove_login_method
from ..services.steam_service import get_steam_summary

SUGGESTED_USERS = 3


def private_profile_response(request, viewer, owner, connection):
    """Заглушка закритого профілю (для профілю та бібліотеки)."""
    return render(request, "library/private_profile.html", {
        "current_user": viewer,
        "profile_user": owner,
        "connection": connection,
        "block_state": block_state(viewer, owner),
        "library_count": LibraryEntry.objects.filter(user=owner).count(),
    })


@library_login_required
def user_list(request):
    current_user = request.library_user
    connections = SocialConnection.objects.filter(models.Q(sender=current_user) | models.Q(receiver=current_user))

    status_by_user = {}
    for connection in connections:
        other_id = connection.receiver_id if connection.sender_id == current_user.id else connection.sender_id
        if connection.status != "rejected":  # після відхилення заявку можна надіслати знову
            status_by_user[other_id] = connection.status
    for blocked_id in UserBlock.objects.filter(blocker=current_user).values_list("blocked_id", flat=True):
        status_by_user[blocked_id] = "blocked"

    # Тих, хто заблокував поточного користувача, у списку не показуємо.
    users = User.objects.exclude(id=current_user.id).exclude(id__in=blocked_by_ids(current_user)).order_by("username")

    return render(request, "library/user_list.html", {
        "current_user": current_user,
        "users_data": [{"user": user, "connection_status": status_by_user.get(user.id)} for user in users],
    })


@library_login_required
def friends(request):
    current_user = request.library_user
    notifications.mark_read(current_user, kinds=[Notification.FRIEND_REQUEST, Notification.FRIEND_ACCEPTED])

    sent_requests = SocialConnection.objects.filter(sender=current_user, status="pending").select_related("receiver")
    received_requests = (
        SocialConnection.objects.filter(receiver=current_user, status="pending").select_related("sender")
    )
    accepted_connections = list(
        SocialConnection.objects
        .filter(status="accepted")
        .filter(models.Q(sender=current_user) | models.Q(receiver=current_user))
        .select_related("sender", "receiver")
    )
    # Статус «у грі» біля друзів; хто зараз грає — першими.
    steam_presence.attach_live(current_user, [
        c.receiver if c.sender_id == current_user.id else c.sender for c in accepted_connections
    ])
    accepted_connections.sort(
        key=lambda c: (c.receiver if c.sender_id == current_user.id else c.sender).live_session is None
    )

    connected_ids = set()
    for sender_id, receiver_id in (
        SocialConnection.objects
        .filter(models.Q(sender=current_user) | models.Q(receiver=current_user))
        .values_list("sender_id", "receiver_id")
    ):
        connected_ids.add(receiver_id if sender_id == current_user.id else sender_id)

    # Пропозиції: друзі друзів, а якщо їх мало — будь-хто, з ким ще немає зв'язку і блокування.
    connected_ids |= hidden_user_ids(current_user)
    my_friends = friend_ids(current_user)
    friends_of_friends = set()
    for sender_id, receiver_id in (
        SocialConnection.objects
        .filter(status="accepted")
        .filter(models.Q(sender_id__in=my_friends) | models.Q(receiver_id__in=my_friends))
        .values_list("sender_id", "receiver_id")
    ):
        candidate = receiver_id if sender_id in my_friends else sender_id
        if candidate != current_user.id and candidate not in connected_ids:
            friends_of_friends.add(candidate)

    suggested = list(User.objects.filter(id__in=friends_of_friends).order_by("username")[:SUGGESTED_USERS])
    if len(suggested) < SUGGESTED_USERS:
        suggested += list(
            User.objects
            .exclude(id=current_user.id)
            .exclude(id__in=connected_ids | friends_of_friends)
            .order_by("username")[:SUGGESTED_USERS - len(suggested)]
        )

    return render(request, "library/friends.html", {
        "current_user": current_user,
        "sent_requests": sent_requests,
        "received_requests": received_requests,
        "accepted_connections": accepted_connections,
        "suggested_users": suggested,
        "friends_count": len(accepted_connections),
        "received_requests_count": received_requests.count(),
        "sent_requests_count": sent_requests.count(),
    })


@require_POST
@library_login_required
def add_friend(request, user_id):
    current_user = request.library_user
    target_user = get_object_or_404(User, id=user_id)

    if current_user.id == target_user.id:
        messages.error(request, "Не можна додати в друзі самого себе.")
        return redirect("library:user_list")

    state = block_state(current_user, target_user)
    if state == "blocked":
        messages.error(request, f"{target_user.username} у вашому чорному списку — спершу розблокуйте.")
        return redirect_to_next(request, "library:friends")
    if state == "blocked_by":
        messages.error(request, "Надіслати заявку цьому користувачу неможливо.")
        return redirect_to_next(request, "library:friends")

    connection = connection_between(current_user, target_user)
    if connection is not None and connection.status == "rejected":
        connection.delete()  # відхилену заявку можна надсилати знову
        connection = None

    if connection is None:
        connection = SocialConnection.objects.create(
            sender=current_user, receiver=target_user, status="pending", created_at=timezone.now()
        )
        notifications.notify_friend_request(connection)
        messages.success(request, f"Заявку в друзі для {target_user.username} надіслано.")
    elif connection.status == "pending" and connection.receiver_id == current_user.id:
        _accept(connection, current_user)  # зустрічна заявка — просто приймаємо
        messages.success(request, f"Ви з {target_user.username} тепер друзі.")
    else:
        messages.info(request, "Заявка або зв’язок з цим користувачем уже існує.")

    return redirect_to_next(request, "library:friends")


def _accept(connection, current_user):
    was_accepted = connection.status == "accepted"
    connection.status = "accepted"
    connection.save()
    if not was_accepted:
        activity.record_friendship(current_user, connection.sender)
        notifications.notify_friend_accepted(connection)


@require_POST
@library_login_required
def accept_connection(request, connection_id):
    current_user = request.library_user
    connection = get_object_or_404(SocialConnection, id=connection_id)

    if connection.receiver_id == current_user.id and block_state(current_user, connection.sender) is None:
        _accept(connection, current_user)
        messages.success(request, "Заявку в друзі прийнято.")

    return redirect("library:friends")


@require_POST
@library_login_required
def reject_connection(request, connection_id):
    current_user = request.library_user
    connection = get_object_or_404(SocialConnection, id=connection_id)

    if connection.receiver_id == current_user.id:
        connection.status = "rejected"
        connection.save()
        notifications.forget_friend_request(connection)
        messages.success(request, "Заявку в друзі відхилено.")

    return redirect("library:friends")


@require_POST
@library_login_required
def delete_connection(request, connection_id):
    current_user = request.library_user
    connection = get_object_or_404(SocialConnection, id=connection_id)

    if current_user.id not in (connection.sender_id, connection.receiver_id):
        return render(request, "library/no_access.html")

    other_user = connection.receiver if connection.sender_id == current_user.id else connection.sender
    connection.delete()

    messages.success(request, f"Користувача {other_user.username} видалено з друзів.")
    return redirect("library:friends")


@require_POST
@library_login_required
def block_user(request, user_id):
    current_user = request.library_user
    target = get_object_or_404(User, id=user_id)
    if target.id == current_user.id:
        messages.error(request, "Не можна заблокувати самого себе.")
        return redirect("library:profile")

    UserBlock.objects.get_or_create(blocker=current_user, blocked=target, defaults={"created_at": timezone.now()})
    # Дружба, заявки й сповіщення між вами зникають (сповіщення-заявки — каскадно разом зі зв'язком).
    SocialConnection.objects.filter(
        models.Q(sender=current_user, receiver=target) | models.Q(sender=target, receiver=current_user)
    ).delete()
    Notification.objects.filter(
        models.Q(user=current_user, actor=target) | models.Q(user=target, actor=current_user)
    ).delete()

    messages.success(request, f"{target.username} додано до чорного списку.")
    return redirect_to_next(request, "library:user_profile", target.id)


@require_POST
@library_login_required
def unblock_user(request, user_id):
    current_user = request.library_user
    target = get_object_or_404(User, id=user_id)
    UserBlock.objects.filter(blocker=current_user, blocked=target).delete()
    messages.success(request, f"{target.username} прибрано з чорного списку.")
    return redirect_to_next(request, "library:user_profile", target.id)


def _profile_extras(user, own=False):
    """Спільні дані свого й чужого профілю."""
    steam_summary = get_steam_summary(user, top_limit=4)
    if own:
        site_achievements.check_quietly(user)  # страховка: досягнення, що залежать від часу («Старожил»)
    site_views = site_achievements.build_views(user)
    return {
        **profile_stats(user),
        "steam_summary": steam_summary,
        "backdrop": profile_backdrop(user, steam_summary),
        "top_genres": top_genres(user),
        "recent_achievements": steam_achievements.recent_achievements(user, limit=10),
        "achievements_count": steam_achievements.achievements_count(user),
        "site_showcase": site_achievements.showcase(user, site_views),
        "site_summary": site_achievements.summary(site_views),
        "site_unlocked": [v for v in site_views if v.unlocked] if own else [],
        "showcase_custom": user.achievement_showcase is not None,
    }


@library_login_required
def profile(request):
    user = request.library_user

    return render(request, "library/profile.html", {
        "user": user,
        "profile_user": user,
        "is_own_profile": True,
        **_profile_extras(user, own=True),
        "live_session": steam_presence.live_for_users(user, [user]).get(user.id),
        "recent_activity": activity.user_activity(user, user),
    })


@library_login_required
def user_profile(request, user_id):
    current_user = request.library_user
    profile_user = get_object_or_404(User, id=user_id)

    if current_user.id == profile_user.id:
        return redirect("library:profile")

    connection = connection_between(current_user, profile_user)

    if not can_view_profile(current_user, profile_user):
        return private_profile_response(request, current_user, profile_user, connection)

    return render(request, "library/user_profile.html", {
        "current_user": current_user,
        "profile_user": profile_user,
        "connection": connection,
        "block_state": block_state(current_user, profile_user),
        **_profile_extras(profile_user),
        "live_session": steam_presence.live_for_users(current_user, [profile_user]).get(profile_user.id),
        "recent_activity": activity.user_activity(current_user, profile_user),
    })


@library_login_required
def edit_profile(request):
    user = request.library_user
    error = None

    if request.method == "POST":
        form = ProfileForm(request.POST, request.FILES, user=user)

        if form.is_valid():
            data = form.cleaned_data
            user.username = data["username"]
            new_email = data["email"] or None
            email_changed = (new_email or "").lower() != (user.email or "").lower()
            if email_changed and new_email is None:
                user.email, user.email_verified_at = None, None
            user.is_private = data["is_private"]
            user.show_activity = data["show_activity"]
            user.show_playing_now = data["show_playing_now"]
            user.notify_friend_playing = data["notify_friend_playing"]
            if data["password"]:
                user.password_hash = make_password(data["password"])
            old_avatar = user.avatar.name if user.avatar else ""
            if data["avatar"]:
                user.avatar = data["avatar"]
            user.save()

            if data["password"]:
                update_session_after_password_change(request, user)
            if data["avatar"] and old_avatar and old_avatar != user.avatar.name:
                delete_unused_file(User, "avatar", old_avatar)

            if email_changed and new_email:
                # Нова адреса діє лише після підтвердження листом; до того лишається стара.
                send_verification_email(request, user, new_email)
                messages.info(request, f"На {new_email} надіслано лист — email зміниться після підтвердження.")
            messages.success(request, "Профіль успішно оновлено.")
            return redirect("library:profile")

        error = form.first_error()

    accounts = {account.provider: account for account in user.external_accounts.all()}
    return render(request, "library/edit_profile.html", {
        "user": user,
        "error": error,
        "steam_account": accounts.get("steam"),
        "google_account": accounts.get("google"),
        "can_remove": {method: can_remove_login_method(user, method) for method in ("steam", "google")},
        "blocked_users": [
            block.blocked
            for block in UserBlock.objects.filter(blocker=user).select_related("blocked").order_by("-created_at")
        ],
    })
