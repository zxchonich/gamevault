"""Поточний користувач, права доступу та дружба.

Аутентифікація власна (не django.contrib.auth): id користувача лежить у сесії
під ключем SESSION_USER_KEY. У view використовуйте декоратори:

    @library_login_required      # request.library_user — поточний користувач
    @admin_required              # те саме + роль admin, інакше no_access.html
"""

from functools import wraps

from django.db import models
from django.shortcuts import redirect, render
from django.utils.crypto import constant_time_compare, salted_hmac
from django.utils.http import url_has_allowed_host_and_scheme

from .models import SocialConnection, User

SESSION_USER_KEY = "library_user_id"
SESSION_AUTH_KEY = "library_auth_hash"


def session_auth_hash(user):
    """Відбиток хешу пароля: після зміни пароля всі старі сесії стають недійсними."""
    return salted_hmac("library.access.session_auth_hash", user.password_hash or "").hexdigest()


def get_current_user(request):
    user_id = request.session.get(SESSION_USER_KEY)

    if not user_id:
        return None

    user = User.objects.select_related("role").filter(id=user_id).first()
    if user is None:
        return None

    stored = request.session.get(SESSION_AUTH_KEY)
    if stored is None:
        # Сесії, створені до появи відбитка, — дописуємо його, а не розлогінюємо.
        request.session[SESSION_AUTH_KEY] = session_auth_hash(user)
    elif not constant_time_compare(stored, session_auth_hash(user)):
        request.session.flush()
        return None

    return user


def log_in(request, user):
    # Новий ключ сесії після входу (захист від фіксації сесії).
    request.session.cycle_key()
    request.session[SESSION_USER_KEY] = user.id
    request.session[SESSION_AUTH_KEY] = session_auth_hash(user)


def update_session_after_password_change(request, user):
    """Поточна сесія лишається активною (новий ключ і відбиток), інші — розлогінюються."""
    request.session.cycle_key()
    request.session[SESSION_AUTH_KEY] = session_auth_hash(user)


def is_admin_user(user):
    return user is not None and user.role is not None and user.role.name == "admin"


def library_login_required(view):
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        user = get_current_user(request)
        if user is None:
            return redirect("library:login")
        request.library_user = user
        return view(request, *args, **kwargs)

    return wrapper


def admin_required(view):
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        user = get_current_user(request)
        if user is None:
            return redirect("library:login")
        if not is_admin_user(user):
            return render(request, "library/no_access.html")
        request.library_user = user
        return view(request, *args, **kwargs)

    return wrapper


def redirect_to_next(request, fallback, *args, **kwargs):
    """Редирект на ?next= / POST next, лише якщо це адреса цього сайту."""
    next_url = request.POST.get("next") or request.GET.get("next")
    if next_url and url_has_allowed_host_and_scheme(
        next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return redirect(next_url)
    return redirect(fallback, *args, **kwargs)


# --- Дружба --------------------------------------------------------------------

def connection_between(user1, user2):
    return SocialConnection.objects.filter(
        models.Q(sender=user1, receiver=user2) | models.Q(sender=user2, receiver=user1)
    ).first()


def are_friends(user1, user2):
    return SocialConnection.objects.filter(status="accepted").filter(
        models.Q(sender=user1, receiver=user2) | models.Q(sender=user2, receiver=user1)
    ).exists()


def friend_ids(user):
    """id друзів користувача (прийняті заявки в обидва боки)."""
    rows = (
        SocialConnection.objects
        .filter(status="accepted")
        .filter(models.Q(sender=user) | models.Q(receiver=user))
        .values_list("sender_id", "receiver_id")
    )
    return {receiver if sender == user.id else sender for sender, receiver in rows}


def can_view_profile(viewer, owner):
    """Чи може viewer бачити профіль/бібліотеку owner (з урахуванням приватності)."""
    if viewer is None:
        return False
    return viewer.id == owner.id or not owner.is_private or are_friends(viewer, owner)
