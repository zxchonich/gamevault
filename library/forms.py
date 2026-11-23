"""Форми для валідації даних. HTML форм поки що пишеться в шаблонах вручну,
тож форми тут лише перевіряють дані й дають тексти помилок (form.first_error())."""

from django import forms

from .models import Game, Genre, LibraryEntry, User
from .services.steam_service import is_valid_appid

REQUIRED = "Заповніть усі обов’язкові поля."


class LibraryForm(forms.Form):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            max_length = getattr(field, "max_length", None)
            if max_length:
                field.error_messages["max_length"] = f"Значення задовге (максимум {max_length} символів)."

    def first_error(self):
        """Перша помилка форми (шаблони показують одне повідомлення)."""
        for errors in self.errors.values():
            return errors[0]
        return None


MIN_PASSWORD_LENGTH = 8
MAX_AVATAR_SIZE = 5 * 1024 * 1024


def password_problem(password, username=""):
    """Текст проблеми з паролем або None (свої повідомлення українською замість валідаторів Django)."""
    from django.contrib.auth.password_validation import CommonPasswordValidator
    from django.core.exceptions import ValidationError

    if len(password) < MIN_PASSWORD_LENGTH:
        return f"Пароль має містити щонайменше {MIN_PASSWORD_LENGTH} символів."
    if password.isdigit():
        return "Пароль не може складатися лише з цифр."
    if username and username.lower() in password.lower():
        return "Пароль не повинен містити логін."
    try:
        CommonPasswordValidator().validate(password)
    except ValidationError:
        return "Цей пароль занадто поширений — придумайте складніший."
    return None


class LoginForm(LibraryForm):
    username = forms.CharField(max_length=100)  # логін або email
    password = forms.CharField(max_length=128)


class PasswordResetRequestForm(LibraryForm):
    email = forms.EmailField(
        max_length=100,
        error_messages={"required": "Вкажіть email.", "invalid": "Вкажіть коректну електронну адресу."},
    )


class SetPasswordForm(LibraryForm):
    password = forms.CharField(max_length=128, error_messages={"required": "Вкажіть новий пароль."})
    password_confirm = forms.CharField(max_length=128, required=False)

    def __init__(self, *args, username="", **kwargs):
        super().__init__(*args, **kwargs)
        self.username = username

    def clean(self):
        data = super().clean()
        if self.errors:
            return data
        if data["password"] != data.get("password_confirm"):
            raise forms.ValidationError("Паролі не збігаються.")
        problem = password_problem(data["password"], self.username)
        if problem:
            raise forms.ValidationError(problem)
        return data


class RegisterForm(LibraryForm):
    username = forms.CharField(max_length=50, error_messages={"required": REQUIRED})
    email = forms.EmailField(
        max_length=100,
        error_messages={"required": REQUIRED, "invalid": "Вкажіть коректну електронну адресу."},
    )
    password = forms.CharField(max_length=128, error_messages={"required": REQUIRED})
    password_confirm = forms.CharField(max_length=128, required=False)

    def clean(self):
        data = super().clean()
        if self.errors:
            return data

        if data["password"] != data.get("password_confirm"):
            raise forms.ValidationError("Паролі не збігаються.")
        problem = password_problem(data["password"], data["username"])
        if problem:
            raise forms.ValidationError(problem)
        if User.objects.filter(username=data["username"]).exists():
            raise forms.ValidationError("Користувач із таким логіном уже існує.")
        if User.objects.filter(email=data["email"]).exists():
            raise forms.ValidationError("Користувач із такою електронною адресою вже існує.")
        return data


class ProfileForm(LibraryForm):
    EMPTY = "Логін та email не можуть бути порожніми."

    username = forms.CharField(max_length=50, error_messages={"required": EMPTY})
    email = forms.EmailField(
        max_length=100,
        required=False,  # без email можна лише акаунту, прив'язаному до Steam/Google
        error_messages={"invalid": "Вкажіть коректну електронну адресу."},
    )
    current_password = forms.CharField(max_length=128, required=False)
    password = forms.CharField(max_length=128, required=False)
    password_confirm = forms.CharField(max_length=128, required=False)
    avatar = forms.ImageField(required=False, error_messages={"invalid_image": "Аватар має бути зображенням."})
    is_private = forms.BooleanField(required=False)
    show_activity = forms.BooleanField(required=False)

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

    def clean(self):
        data = super().clean()
        if self.errors:
            return data

        others = User.objects.exclude(id=self.user.id)
        if others.filter(username=data["username"]).exists():
            raise forms.ValidationError("Користувач із таким логіном уже існує.")
        if not data["email"] and not self.user.external_accounts.exists():
            raise forms.ValidationError(self.EMPTY)
        if data["email"] and others.filter(email=data["email"]).exists():
            raise forms.ValidationError("Користувач із таким email уже існує.")
        if data["password"]:
            from django.contrib.auth.hashers import check_password

            # Акаунт зі Steam/Google без пароля задає його вперше — поточного пароля немає.
            if self.user.has_usable_password and not check_password(data["current_password"], self.user.password_hash):
                raise forms.ValidationError("Щоб змінити пароль, правильно вкажіть поточний.")
            if data["password"] != data["password_confirm"]:
                raise forms.ValidationError("Паролі не збігаються.")
            problem = password_problem(data["password"], data["username"])
            if problem:
                raise forms.ValidationError(problem)
        avatar = data.get("avatar")
        if avatar and avatar.size > MAX_AVATAR_SIZE:
            raise forms.ValidationError("Аватар завеликий — до 5 МБ.")
        return data


class GameRequestForm(LibraryForm):
    title = forms.CharField(max_length=150, error_messages={"required": "Вкажіть назву гри."})
    description = forms.CharField(required=False)


class ReviewForm(LibraryForm):
    score = forms.IntegerField(
        min_value=1,
        max_value=10,
        error_messages={key: "Оцінка має бути від 1 до 10." for key in ("required", "invalid", "min_value", "max_value")},
    )
    text = forms.CharField(required=False)


class StatusForm(LibraryForm):
    status = forms.ChoiceField(choices=LibraryEntry.STATUS_CHOICES)


class GenreForm(LibraryForm):
    name = forms.CharField(max_length=50, error_messages={"required": "Назва жанру не може бути порожньою."})

    def clean_name(self):
        name = self.cleaned_data["name"]
        if Genre.objects.filter(name__iexact=name).exists():
            raise forms.ValidationError("Такий жанр уже існує.")
        return name


class GameForm(LibraryForm):
    title = forms.CharField(max_length=150, error_messages={"required": "Назва гри обов’язкова."})
    description = forms.CharField(required=False)
    developer = forms.CharField(max_length=100, required=False)
    release_date = forms.DateField(required=False, error_messages={"invalid": "Некоректна дата виходу."})
    steam_appid = forms.CharField(max_length=20, required=False)
    steam_header_image = forms.CharField(max_length=500, required=False)
    download_steam_poster = forms.BooleanField(required=False)

    def __init__(self, *args, game=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.game = game

    def clean_steam_appid(self):
        appid = self.cleaned_data["steam_appid"]
        if not appid:
            return None
        if not is_valid_appid(appid):
            raise forms.ValidationError("Steam AppID має складатися лише з цифр.")

        duplicate = Game.objects.filter(steam_appid=appid)
        if self.game is not None:
            duplicate = duplicate.exclude(id=self.game.id)
        duplicate = duplicate.first()
        if duplicate:
            raise forms.ValidationError(f'Steam AppID {appid} уже прив’язаний до гри "{duplicate.title}".')
        return appid

    def form_data(self):
        """Введені значення для повторного показу форми (шаблон читає form_data.*)."""
        return {
            "title": self.data.get("title", "").strip(),
            "description": self.data.get("description", "").strip(),
            "developer": self.data.get("developer", "").strip(),
            "release_date": self.data.get("release_date", "").strip(),
            "steam_appid": self.data.get("steam_appid", "").strip(),
            "steam_header_image": self.data.get("steam_header_image", "").strip(),
            "download_steam_poster": self.data.get("download_steam_poster") == "1",
        }

    def selected_genre_ids(self):
        return {int(g) for g in self.data.getlist("genres") if str(g).isdigit()}
