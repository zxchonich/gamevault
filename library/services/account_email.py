"""Листи акаунта: підтвердження email і скидання пароля.

Токени — підписані ключем сайту дані (django.core.signing), окрема таблиця не потрібна:
  * підтвердження: {id користувача, email} — дійсне VERIFY_MAX_AGE і лише поки email не змінився
    на інший (для зміни email у налаштуваннях у токені лежить нова адреса);
  * скидання пароля: {id, відбиток поточного хешу пароля} — стає недійсним, щойно пароль змінено.
"""

from email.utils import make_msgid

from django.conf import settings
from django.core import signing
from django.core.cache import cache
from django.core.mail import EmailMessage
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.crypto import constant_time_compare, salted_hmac

from library.models import User

VERIFY_SALT = "library.email-verify"
RESET_SALT = "library.password-reset"
VERIFY_MAX_AGE = 3 * 24 * 60 * 60
RESET_MAX_AGE = 24 * 60 * 60
RESEND_INTERVAL = 60


class TokenError(Exception):
    """Посилання недійсне або застаріле (текст — для користувача)."""


# --- Токени ------------------------------------------------------------------------

def make_verify_token(user, email):
    return signing.dumps({"u": user.id, "e": email}, salt=VERIFY_SALT)


def read_verify_token(token):
    """(user, email) з токена підтвердження або TokenError."""
    try:
        data = signing.loads(token, salt=VERIFY_SALT, max_age=VERIFY_MAX_AGE)
    except signing.SignatureExpired:
        raise TokenError("Термін дії посилання минув. Надішліть лист ще раз.")
    except signing.BadSignature:
        raise TokenError("Посилання недійсне.")
    user = User.objects.filter(id=data.get("u")).first()
    if user is None or not data.get("e"):
        raise TokenError("Посилання недійсне.")
    return user, data["e"]


def _password_fingerprint(user):
    return salted_hmac(RESET_SALT, user.password_hash or "").hexdigest()[:20]


def make_reset_token(user):
    return signing.dumps({"u": user.id, "p": _password_fingerprint(user)}, salt=RESET_SALT)


def read_reset_token(token):
    """Користувач із токена скидання пароля або TokenError."""
    try:
        data = signing.loads(token, salt=RESET_SALT, max_age=RESET_MAX_AGE)
    except signing.SignatureExpired:
        raise TokenError("Термін дії посилання минув. Запросіть новий лист.")
    except signing.BadSignature:
        raise TokenError("Посилання недійсне.")
    user = User.objects.filter(id=data.get("u")).first()
    if user is None or not constant_time_compare(data.get("p", ""), _password_fingerprint(user)):
        raise TokenError("Посилання вже використане або недійсне. Запросіть новий лист.")
    return user


# --- Надсилання ------------------------------------------------------------------------

def _send(subject, template, to, context):
    body = render_to_string(f"library/emails/{template}.txt", context)
    # Message-ID задаємо самі: інакше Django для нього викликає socket.getfqdn(), а на Windows
    # перший такий виклик може тривати секунди — і реєстрація «зависає».
    domain = settings.DEFAULT_FROM_EMAIL.rsplit("@", 1)[-1].strip("> ") or "gamevault.local"
    EmailMessage(subject, body, settings.DEFAULT_FROM_EMAIL, [to],
                 headers={"Message-ID": make_msgid(domain=domain)}).send()


def send_verification_email(request, user, email):
    link = request.build_absolute_uri(reverse("library:verify_email", args=[make_verify_token(user, email)]))
    is_change = bool(user.email_verified_at) or (user.email and user.email.lower() != email.lower())
    _send(
        "Підтвердіть email — GameVault",
        "verify_email",
        email,
        {"user": user, "link": link, "is_change": is_change, "days": VERIFY_MAX_AGE // 86400},
    )


def send_password_reset_email(request, user):
    link = request.build_absolute_uri(reverse("library:password_reset_confirm", args=[make_reset_token(user)]))
    _send("Скидання пароля — GameVault", "password_reset", user.email, {"user": user, "link": link})


def resend_allowed(key):
    """Не частіше разу на RESEND_INTERVAL секунд для одного ключа (користувач, адреса)."""
    return cache.add(f"email-resend:{key}", 1, RESEND_INTERVAL)
