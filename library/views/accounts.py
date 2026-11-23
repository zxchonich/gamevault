"""Вхід, вихід і реєстрація (власна аутентифікація, див. library/access.py)."""

from django.contrib.auth.hashers import check_password, make_password
from django.core.cache import cache
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from ..access import log_in
from ..forms import LoginForm, RegisterForm
from ..models import Role, User


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


def login_view(request):
    error = None

    if request.method == "POST":
        form = LoginForm(request.POST)
        username = request.POST.get("username", "").strip()

        if _login_locked(request, username):
            error = "Забагато невдалих спроб входу. Спробуйте через 10 хвилин."
            return render(request, "library/login.html", {"error": error}, status=429)

        user = None
        if form.is_valid():
            user = User.objects.filter(username=form.cleaned_data["username"]).first()

        if user and check_password(form.cleaned_data["password"], user.password_hash):
            cache.delete(_login_keys(request, username)[0])
            log_in(request, user)
            return redirect("library:home")

        _register_login_failure(request, username)
        error = "Неправильний логін або пароль."

    return render(request, "library/login.html", {"error": error})


@require_POST
def logout_view(request):
    request.session.flush()
    return redirect("library:home")


def register_view(request):
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
            user = User.objects.create(
                role=role,
                username=data["username"],
                email=data["email"],
                password_hash=make_password(data["password"]),
                created_at=timezone.now(),
            )
            log_in(request, user)
            return redirect("library:profile")

    return render(request, "library/register.html", {"error": error})
