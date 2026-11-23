"""Вхід, вихід, реєстрація, підтвердження email і скидання пароля
(власна аутентифікація, див. library/access.py; листи — services/account_email.py).

Акаунт із паролем без підтвердженого email не входить: після реєстрації чи спроби входу
відкривається сторінка «Підтвердіть email», а користувач лишається гостем. Його id лежить у
сесії під PENDING_USER_KEY лише для того, щоб показати адресу й надіслати лист ще раз.
"""

from django.contrib import messages
from django.contrib.auth.hashers import check_password, make_password
from django.core.cache import cache
from django.db import IntegrityError, models
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from ..access import get_current_user, log_in, needs_email_verification
from ..forms import LoginForm, PasswordResetRequestForm, RegisterForm, SetPasswordForm
from ..models import Role, User
from ..services.account_email import (
    TokenError,
    read_reset_token,
    read_verify_token,
    resend_allowed,
    send_password_reset_email,
    send_verification_email,
)

PENDING_USER_KEY = "library_pending_user_id"

# Захист від перебору паролів: після LOGIN_MAX_FAILURES невдалих спроб за LOGIN_LOCK_SECONDS
# вхід для цього логіна (і окремо для цієї IP-адреси) блокується до кінця вікна.
LOGIN_MAX_FAILURES = 5
LOGIN_LOCK_SECONDS = 10 * 60
IP_MAX_FAILURES = 20


def _login_keys(request, username):
    ip = request.META.get("REMOTE_ADDR", "")
    return f"login-fail:user:{username.lower()}", f"login-fail:ip:{ip}"


def _login_locked(request, username):
    user_key, ip_key = _login_keys(request, username)
    return cache.get(user_key, 0) >= LOGIN_MAX_FAILURES or cache.get(ip_key, 0) >= IP_MAX_FAILURES


def _register_login_failure(request, username):
    for key in _login_keys(request, username):
        cache.add(key, 0, LOGIN_LOCK_SECONDS)  # вікно рахується від першої невдалої спроби
        try:
            cache.incr(key)
        except ValueError:
            cache.set(key, 1, LOGIN_LOCK_SECONDS)


def _send_pending_verification(request, user):
    """Надсилає лист підтвердження й запам'ятовує користувача для сторінки «Підтвердіть email»."""
    request.session[PENDING_USER_KEY] = user.id
    if resend_allowed(f"user:{user.id}"):
        send_verification_email(request, user, user.email)
    return redirect("library:verify_pending")


def login_view(request):
    if get_current_user(request):
        return redirect("library:home")
    error = None

    if request.method == "POST":
        form = LoginForm(request.POST)
        login = request.POST.get("username", "").strip()

        if _login_locked(request, login):
            error = "Забагато невдалих спроб входу. Спробуйте через 10 хвилин."
            return render(request, "library/login.html", {"error": error}, status=429)

        user = None
        if form.is_valid():
            login = form.cleaned_data["username"]
            # Логін або email (обидва унікальні; порівняння без урахування регістру — колація БД).
            user = User.objects.filter(models.Q(username=login) | models.Q(email=login)).first()

        if user and check_password(form.cleaned_data["password"], user.password_hash):
            cache.delete(_login_keys(request, login)[0])
            if needs_email_verification(user):
                return _send_pending_verification(request, user)
            log_in(request, user)
            return redirect("library:home")

        _register_login_failure(request, login)
        error = "Неправильний логін або пароль."

    return render(request, "library/login.html", {"error": error})


@require_POST
def logout_view(request):
    request.session.flush()
    return redirect("library:home")


def register_view(request):
    if get_current_user(request):
        return redirect("library:home")
    error = None

    if request.method == "POST":
        form = RegisterForm(request.POST)
        role = Role.objects.filter(name="user").first()

        if not form.is_valid():
            error = form.first_error()
        elif role is None:
            error = "У базі даних немає ролі user. Додайте її через адмінку."
        else:
            data = form.cleaned_data
            try:
                user = User.objects.create(
                    role=role,
                    username=data["username"],
                    email=data["email"],
                    password_hash=make_password(data["password"]),
                    created_at=timezone.now(),
                )
            except IntegrityError:
                error = "Користувач із таким логіном або email уже існує."
            else:
                return _send_pending_verification(request, user)

    return render(request, "library/register.html", {"error": error})


def verify_pending(request):
    """«Підтвердіть email»: адреса, на яку пішов лист, і кнопка «Надіслати ще раз»."""
    user = User.objects.filter(id=request.session.get(PENDING_USER_KEY)).first()
    if user is None or not needs_email_verification(user):
        request.session.pop(PENDING_USER_KEY, None)
        return redirect("library:login")

    if request.method == "POST":
        if resend_allowed(f"user:{user.id}"):
            send_verification_email(request, user, user.email)
            messages.success(request, "Лист надіслано ще раз.")
        else:
            messages.error(request, "Лист щойно надіслано — зачекайте хвилину перед повторною спробою.")
        return redirect("library:verify_pending")

    return render(request, "library/verify_pending.html", {"pending_user": user})


def verify_email(request, token):
    """Посилання з листа: підтверджує email (або нову адресу після зміни) і входить в акаунт."""
    try:
        user, email = read_verify_token(token)
    except TokenError as exc:
        return render(request, "library/token_invalid.html", {"error": str(exc)}, status=400)

    if (user.email or "").lower() != email.lower():
        # Зміна email у налаштуваннях: адреса могла стати зайнятою, поки лист ішов.
        if User.objects.filter(email=email).exclude(id=user.id).exists():
            return render(request, "library/token_invalid.html", {
                "error": "Ця адреса вже використовується іншим акаунтом.",
            }, status=400)
        user.email = email
        user.email_verified_at = timezone.now()
        user.save(update_fields=["email", "email_verified_at"])
        messages.success(request, f"Email змінено на {email}.")
    elif user.email_verified_at is None:
        user.email_verified_at = timezone.now()
        user.save(update_fields=["email_verified_at"])
        messages.success(request, "Email підтверджено. Ласкаво просимо до GameVault!")
    else:
        messages.success(request, "Email уже підтверджено.")

    request.session.pop(PENDING_USER_KEY, None)
    current = get_current_user(request)
    if current is None or current.id != user.id:
        log_in(request, user)
    return redirect("library:profile")


def password_reset_request(request):
    sent_to = None
    if request.method == "POST":
        form = PasswordResetRequestForm(request.POST)
        if form.is_valid():
            email = form.cleaned_data["email"]
            user = User.objects.filter(email=email).first()
            # Відповідь однакова, чи є такий акаунт, чи ні — щоб не можна було перебирати адреси.
            if user and resend_allowed(f"reset:{user.id}"):
                send_password_reset_email(request, user)
            sent_to = email
        else:
            messages.error(request, form.first_error())
    return render(request, "library/password_reset.html", {"sent_to": sent_to})


def password_reset_confirm(request, token):
    try:
        user = read_reset_token(token)
    except TokenError as exc:
        return render(request, "library/token_invalid.html", {"error": str(exc)}, status=400)

    error = None
    if request.method == "POST":
        form = SetPasswordForm(request.POST, username=user.username)
        if form.is_valid():
            user.password_hash = make_password(form.cleaned_data["password"])
            fields = ["password_hash"]
            if user.email_verified_at is None:
                # Лист дійшов — отже, адреса належить користувачу.
                user.email_verified_at = timezone.now()
                fields.append("email_verified_at")
            user.save(update_fields=fields)
            request.session.pop(PENDING_USER_KEY, None)
            log_in(request, user)  # нова сесія; решта сесій недійсні — змінився хеш пароля
            messages.success(request, "Пароль змінено.")
            return redirect("library:profile")
        error = form.first_error()

    return render(request, "library/password_reset_confirm.html", {"reset_user": user, "error": error})
