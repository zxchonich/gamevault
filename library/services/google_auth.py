"""Вхід через Google (OAuth 2.0 authorization code + PKCE).

Схема: google_connect кладе в сесію випадковий state і code_verifier та веде на Google;
google_callback перевіряє state, обмінює code на access token (з code_verifier) і бере
профіль з userinfo-ендпоінту Google напряму по HTTPS — тому id_token окремо не перевіряємо.
"""

import base64
import hashlib
import secrets
import urllib.parse

import requests
from django.conf import settings
from django.urls import reverse

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
REQUEST_TIMEOUT = 10

SESSION_STATE_KEY = "google_oauth_state"
SESSION_VERIFIER_KEY = "google_oauth_verifier"


class GoogleError(Exception):
    """Помилка входу через Google (текст — для користувача)."""


def is_configured():
    return bool(settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET)


def _redirect_uri(request):
    return request.build_absolute_uri(reverse("library:google_callback"))


def build_google_login_url(request):
    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    request.session[SESSION_STATE_KEY] = state
    request.session[SESSION_VERIFIER_KEY] = verifier

    params = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "redirect_uri": _redirect_uri(request),
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "prompt": "select_account",
    }
    return AUTH_URL + "?" + urllib.parse.urlencode(params)


def fetch_google_user(request):
    """Перевіряє відповідь Google і повертає профіль {"sub", "email", "email_verified", "name", "picture"}."""
    state = request.session.pop(SESSION_STATE_KEY, None)
    verifier = request.session.pop(SESSION_VERIFIER_KEY, None)

    if request.GET.get("error"):
        raise GoogleError("Вхід через Google скасовано.")
    if not state or not secrets.compare_digest(state, request.GET.get("state", "")):
        raise GoogleError("Сесія входу через Google застаріла. Спробуйте ще раз.")
    code = request.GET.get("code")
    if not code:
        raise GoogleError("Google не повернув код входу. Спробуйте ще раз.")

    try:
        token_response = requests.post(TOKEN_URL, data={
            "code": code,
            "client_id": settings.GOOGLE_CLIENT_ID,
            "client_secret": settings.GOOGLE_CLIENT_SECRET,
            "redirect_uri": _redirect_uri(request),
            "grant_type": "authorization_code",
            "code_verifier": verifier,
        }, timeout=REQUEST_TIMEOUT)
        token_response.raise_for_status()
        access_token = token_response.json()["access_token"]

        info_response = requests.get(
            USERINFO_URL, headers={"Authorization": f"Bearer {access_token}"}, timeout=REQUEST_TIMEOUT
        )
        info_response.raise_for_status()
        info = info_response.json()
    except (requests.RequestException, ValueError, KeyError) as exc:
        raise GoogleError("Не вдалося отримати дані з Google. Спробуйте пізніше.") from exc

    if not info.get("sub"):
        raise GoogleError("Google повернув неповні дані профілю.")
    return {
        "sub": str(info["sub"]),
        "email": (info.get("email") or "").strip() or None,
        "email_verified": bool(info.get("email_verified")),
        "name": info.get("name") or "",
        "picture": info.get("picture"),
    }
