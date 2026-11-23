"""Вхід, реєстрація та прив'язка через Google (див. services/google_auth.py)."""

from django.contrib import messages
from django.shortcuts import redirect
from django.views.decorators.http import require_POST

from ..access import get_current_user, library_login_required, log_in, redirect_to_next
from ..models import ExternalAccount, User
from ..services.google_auth import GoogleError, build_google_login_url, fetch_google_user, is_configured
from ..services.social_auth import can_remove_login_method, create_social_user


def _account_defaults(info):
    return {"username": info["email"] or info["name"], "profile_url": None, "avatar_url": info["picture"]}


def google_connect(request):
    if not is_configured():
        messages.error(request, "Вхід через Google поки не налаштовано.")
        return redirect("library:login")
    return redirect(build_google_login_url(request))


def google_callback(request):
    user = get_current_user(request)
    try:
        info = fetch_google_user(request)
    except GoogleError as exc:
        messages.error(request, str(exc))
        return redirect("library:edit_profile" if user else "library:login")

    existing = ExternalAccount.objects.select_related("user").filter(provider="google", external_user_id=info["sub"]).first()

    if user is not None:
        # Прив'язка до поточного акаунта.
        if existing and existing.user_id != user.id:
            messages.error(request, "Цей Google-акаунт уже прив'язаний до іншого користувача GameVault.")
        else:
            ExternalAccount.objects.update_or_create(
                user=user, provider="google",
                defaults={"external_user_id": info["sub"], **_account_defaults(info)},
            )
            messages.success(request, "Google підключено — тепер можна входити через нього.")
        return redirect("library:edit_profile")

    if existing:
        log_in(request, existing.user)
        return redirect("library:home")

    if info["email"] and info["email_verified"]:
        owner = User.objects.filter(email=info["email"]).first()
        if owner is not None:
            # Пошта вже належить акаунту: входимо й прив'язуємо Google, лише якщо вона там підтверджена —
            # інакше хтось міг зареєструвати чужу адресу й чекати, поки власник прийде через Google.
            if not owner.is_email_verified:
                messages.error(
                    request,
                    "Акаунт із цією поштою вже існує, але пошту в ньому не підтверджено. "
                    "Підтвердіть її з листа або скиньте пароль — і тоді входьте через Google.",
                )
                return redirect("library:login")
            ExternalAccount.objects.create(user=owner, provider="google", external_user_id=info["sub"], **_account_defaults(info))
            log_in(request, owner)
            messages.success(request, "Google прив'язано до вашого акаунта.")
            return redirect("library:home")

    verified_email = info["email"] if info["email_verified"] else None
    new_user = create_social_user(
        "google",
        info["sub"],
        username_hint=info["name"] or (info["email"] or "").split("@")[0],
        email=verified_email,
        email_verified=bool(verified_email),
        avatar_url=info["picture"],
        account_defaults=_account_defaults(info),
    )
    log_in(request, new_user)
    messages.success(
        request,
        f"Акаунт {new_user.username} створено через Google. Логін і пароль можна змінити в налаштуваннях.",
    )
    return redirect("library:profile")


@require_POST
@library_login_required
def google_disconnect(request):
    user = request.library_user
    if not can_remove_login_method(user, "google"):
        messages.error(
            request,
            "Google — єдиний спосіб входу в цей акаунт. Спершу задайте пароль і підтвердіть email або підключіть Steam.",
        )
    else:
        ExternalAccount.objects.filter(user=user, provider="google").delete()
        messages.success(request, "Google відключено.")
    return redirect_to_next(request, "library:edit_profile")
