"""Вхід і реєстрація через Steam/Google: створення акаунта «в кілька кліків» і способи входу.

Новий акаунт отримує логін із ніку/імені провайдера (з суфіксом _2, _3…, якщо зайнятий),
аватар провайдера й непридатний пароль — усе інше користувач змінює в налаштуваннях.
"""

import re

from django.contrib.auth.hashers import make_password
from django.core.files.base import ContentFile
from django.db import IntegrityError, transaction
from django.utils import timezone

from library.models import ExternalAccount, Role, User

USERNAME_MAX = 50
PROVIDER_LABELS = {"steam": "Steam", "google": "Google"}


def unique_username(hint):
    base = re.sub(r"\s+", " ", (hint or "").strip())[:USERNAME_MAX - 4].strip() or "player"
    candidate, number = base, 1
    while User.objects.filter(username__iexact=candidate).exists():
        number += 1
        candidate = f"{base}_{number}"
    return candidate


def _attach_avatar(user, avatar_url):
    """Аватар провайдера — у звичайне поле avatar (далі користувач може замінити)."""
    if not avatar_url:
        return
    from library.services.steam_service import _download_image

    content = _download_image(avatar_url)
    if content:
        user.avatar.save(f"user_{user.id}.jpg", ContentFile(content), save=True)


def create_social_user(provider, external_id, *, username_hint, email=None, email_verified=False,
                       avatar_url=None, account_defaults=None):
    """Створює користувача й ExternalAccount провайдера. Повертає користувача."""
    role = Role.objects.get(name="user")
    for _ in range(3):  # логін могли зайняти між перевіркою й вставкою
        try:
            with transaction.atomic():
                user = User.objects.create(
                    role=role,
                    username=unique_username(username_hint),
                    email=email or None,
                    email_verified_at=timezone.now() if email and email_verified else None,
                    password_hash=make_password(None),
                    created_at=timezone.now(),
                )
                ExternalAccount.objects.create(
                    user=user, provider=provider, external_user_id=external_id, **(account_defaults or {})
                )
            break
        except IntegrityError:
            if email and User.objects.filter(email=email).exists():
                raise
    else:
        raise IntegrityError("Не вдалося підібрати вільний логін.")
    _attach_avatar(user, avatar_url)
    return user


def login_methods(user):
    """Чим користувач може увійти: {"password", "steam", "google"} (пароль — лише з підтвердженим email)."""
    methods = set(user.external_accounts.values_list("provider", flat=True))
    if user.has_usable_password and user.is_email_verified:
        methods.add("password")
    return methods


def can_remove_login_method(user, method):
    """Не даємо відключити останній спосіб входу."""
    return bool(login_methods(user) - {method})
