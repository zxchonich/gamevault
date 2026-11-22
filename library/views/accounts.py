"""Вхід, вихід і реєстрація (власна аутентифікація, див. library/access.py)."""

from django.contrib.auth.hashers import check_password, make_password
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from ..access import log_in
from ..forms import LoginForm, RegisterForm
from ..models import Role, User


def login_view(request):
    error = None

    if request.method == "POST":
        form = LoginForm(request.POST)
        user = None
        if form.is_valid():
            user = User.objects.filter(username=form.cleaned_data["username"]).first()

        if user and check_password(form.cleaned_data["password"], user.password_hash):
            log_in(request, user)
            return redirect("library:home")

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
