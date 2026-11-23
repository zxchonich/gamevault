"""Користувачі, друзі, профілі."""

from django.contrib import messages
from django.contrib.auth.hashers import make_password
from django.db import models
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from ..access import (
    can_view_profile,
    connection_between,
    friend_ids,
    library_login_required,
    update_session_after_password_change,
)
from ..forms import ProfileForm
from ..models import LibraryEntry, SocialConnection, User
from ..selectors import profile_backdrop, profile_stats
from ..storage import delete_unused_file
from ..services import activity
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
        "library_count": LibraryEntry.objects.filter(user=owner).count(),
    })


@library_login_required
def user_list(request):
    current_user = request.library_user
    connections = SocialConnection.objects.filter(models.Q(sender=current_user) | models.Q(receiver=current_user))

    status_by_user = {}
    for connection in connections:
        other_id = connection.receiver_id if connection.sender_id == current_user.id else connection.sender_id
        status_by_user[other_id] = connection.status

    users = User.objects.exclude(id=current_user.id).order_by("username")

    return render(request, "library/user_list.html", {
        "current_user": current_user,
        "users_data": [{"user": user, "connection_status": status_by_user.get(user.id)} for user in users],
    })


@library_login_required
def friends(request):
    current_user = request.library_user

    sent_requests = SocialConnection.objects.filter(sender=current_user, status="pending").select_related("receiver")
    received_requests = (
        SocialConnection.objects.filter(receiver=current_user, status="pending").select_related("sender")
    )
    accepted_connections = (
        SocialConnection.objects
        .filter(status="accepted")
        .filter(models.Q(sender=current_user) | models.Q(receiver=current_user))
        .select_related("sender", "receiver")
    )

    connected_ids = set()
    for sender_id, receiver_id in (
        SocialConnection.objects
        .filter(models.Q(sender=current_user) | models.Q(receiver=current_user))
        .values_list("sender_id", "receiver_id")
    ):
        connected_ids.add(receiver_id if sender_id == current_user.id else sender_id)

    # Пропозиції: друзі друзів, а якщо їх мало — будь-хто, з ким ще немає зв'язку.
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
        "friends_count": accepted_connections.count(),
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

    if connection_between(current_user, target_user) is None:
        SocialConnection.objects.create(
            sender=current_user, receiver=target_user, status="pending", created_at=timezone.now()
        )
        messages.success(request, f"Заявку в друзі для {target_user.username} надіслано.")
    else:
        messages.info(request, "Заявка або зв’язок з цим користувачем уже існує.")

    return redirect("library:friends")


@require_POST
@library_login_required
def accept_connection(request, connection_id):
    current_user = request.library_user
    connection = get_object_or_404(SocialConnection, id=connection_id)

    if connection.receiver_id == current_user.id:
        if connection.status != "accepted":
            activity.record_friendship(current_user, connection.sender)
        connection.status = "accepted"
        connection.save()
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


def _profile_extras(user):
    """Спільні дані свого й чужого профілю."""
    steam_summary = get_steam_summary(user, top_limit=4)
    return {
        **profile_stats(user),
        "steam_summary": steam_summary,
        "backdrop": profile_backdrop(user, steam_summary),
        "top_genres": top_genres(user),
    }


@library_login_required
def profile(request):
    user = request.library_user

    return render(request, "library/profile.html", {
        "user": user,
        "profile_user": user,
        "is_own_profile": True,
        **_profile_extras(user),
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
        **_profile_extras(profile_user),
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
    })
