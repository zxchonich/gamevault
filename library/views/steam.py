"""Представлення інтеграції зі Steam: підключення, синхронізація, Steam-бібліотека,
пропозиції ігор у каталог і зіставлення каталогу зі Steam для адміністратора."""

from django.contrib import messages
from django.core.paginator import Paginator
from django.db import models
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from ..access import (
    admin_required,
    can_view_profile,
    get_current_user,
    library_login_required,
    log_in,
    redirect_to_next,
)
from ..models import ExternalAccount, ExternalLibraryItem, Game, GameRequest, LibraryEntry, User
from ..selectors import get_status_label
from ..services import activity
from ..services.social_auth import can_remove_login_method, create_social_user
from ..services.steam_service import (
    SteamError,
    attach_steam_apps,
    build_steam_login_url,
    extract_steam_id_from_openid,
    get_steam_profile,
    is_valid_appid,
    link_game_to_steam_owners,
    normalize_title,
    sync_steam_library,
    validate_steam_openid_response,
)

STEAM_LIBRARY_PAGE_SIZE = 30  # ділиться на 1, 2, 3, 5 і 6 колонок .gv-steam-grid — останній ряд завжди повний


def _sync_and_report(request, user, steam_account):
    try:
        result = sync_steam_library(user, steam_account)
    except SteamError as exc:
        messages.error(request, str(exc))
        return

    activity.record_steam_import(user, result["added_to_library_count"])

    text = (
        f"Steam синхронізовано: {result['synced_count']} ігор отримано, "
        f"{result['added_to_library_count']} додано до бібліотеки GameVault."
    )
    if result["removed_count"]:
        text += f" Прибрано ігор, яких більше немає в Steam: {result['removed_count']}."
    if result.get("details_pending"):
        text += (
            f" Обкладинки та жанри завантажено для {result['details_fetched']} ігор, "
            f"ще {result['details_pending']} — під час наступних синхронізацій."
        )

    messages.success(request, text)


# --- Підключення та синхронізація ---------------------------------------------

def steam_connect(request):
    """Увійти / зареєструватися через Steam (гість) або прив'язати Steam (увійшов)."""
    return redirect(build_steam_login_url(request))


def _steam_account_defaults(steam_id, steam_profile):
    return {
        "username": steam_profile["username"] if steam_profile else f"Steam user {steam_id}",
        "profile_url": steam_profile["profile_url"] if steam_profile else f"https://steamcommunity.com/profiles/{steam_id}",
        "avatar_url": steam_profile["avatar_url"] if steam_profile else None,
    }


def steam_callback(request):
    user = get_current_user(request)
    fail_redirect = "library:profile" if user else "library:login"

    if not validate_steam_openid_response(request):
        messages.error(request, "Не вдалося підтвердити вхід через Steam. Спробуйте ще раз.")
        return redirect(fail_redirect)

    steam_id = extract_steam_id_from_openid(request)

    if not steam_id:
        messages.error(request, "Steam повернув некоректний ідентифікатор акаунта.")
        return redirect(fail_redirect)

    existing = ExternalAccount.objects.select_related("user").filter(provider="steam", external_user_id=steam_id).first()

    if user is None:
        return _steam_login_or_signup(request, steam_id, existing)

    if existing and existing.user_id != user.id:
        messages.error(request, "Цей Steam-акаунт уже прив'язаний до іншого користувача GameVault.")
        return redirect("library:profile")

    steam_account, _ = ExternalAccount.objects.update_or_create(
        user=user,
        provider="steam",
        defaults={"external_user_id": steam_id, **_steam_account_defaults(steam_id, get_steam_profile(steam_id))},
    )

    messages.success(request, "Steam-акаунт підключено.")

    # Одразу імпортуємо ігри, щоб не треба було окремо натискати "Синхронізувати".
    _sync_and_report(request, user, steam_account)

    return redirect("library:steam_library")


def _steam_login_or_signup(request, steam_id, existing):
    """Гість: вхід у прив'язаний акаунт або новий акаунт зі Steam в один клік."""
    if existing:
        log_in(request, existing.user)
        return redirect("library:home")

    steam_profile = get_steam_profile(steam_id)
    defaults = _steam_account_defaults(steam_id, steam_profile)
    user = create_social_user(
        "steam",
        steam_id,
        username_hint=steam_profile["username"] if steam_profile else "",
        avatar_url=(steam_profile or {}).get("avatar_url"),
        account_defaults=defaults,
    )
    log_in(request, user)
    messages.success(
        request,
        f"Акаунт {user.username} створено через Steam. Логін, email і пароль можна змінити в налаштуваннях.",
    )
    _sync_and_report(request, user, user.external_accounts.get(provider="steam"))
    return redirect("library:profile")


@require_POST
@library_login_required
def steam_disconnect(request):
    user = request.library_user

    if not can_remove_login_method(user, "steam"):
        messages.error(
            request,
            "Steam — єдиний спосіб входу в цей акаунт. Спершу задайте пароль і підтвердіть email "
            "або підключіть Google у налаштуваннях.",
        )
        return redirect_to_next(request, "library:profile")

    # Імпортовані ігри Steam (external_library_items) видаляються каскадно;
    # записи в бібліотеці GameVault залишаються.
    ExternalAccount.objects.filter(user=user, provider="steam").delete()

    messages.success(request, "Steam-акаунт відв'язано.")
    return redirect("library:profile")


@require_POST
@library_login_required
def steam_sync_library(request):
    user = request.library_user

    steam_account = ExternalAccount.objects.filter(user=user, provider="steam").first()

    if not steam_account:
        messages.error(request, "Спочатку підключіть Steam-акаунт.")
        return redirect("library:profile")

    _sync_and_report(request, user, steam_account)
    return redirect_to_next(request, "library:profile")


# --- Steam-бібліотека --------------------------------------------------------

def _render_steam_library(request, viewer, owner):
    is_own = viewer.id == owner.id
    steam_account = ExternalAccount.objects.filter(user=owner, provider="steam").first()

    query = request.GET.get("q", "").strip()
    catalog_filter = request.GET.get("catalog", "")
    sort = request.GET.get("sort", "playtime")

    all_items = ExternalLibraryItem.objects.filter(user=owner, provider="steam")
    catalog_appids = set(
        Game.objects.exclude(steam_appid__isnull=True).exclude(steam_appid="")
        .values_list("steam_appid", flat=True)
    )

    items = all_items
    if query:
        items = items.filter(game_title__icontains=query)
    if catalog_filter == "in":
        items = items.filter(external_game_id__in=catalog_appids)
    elif catalog_filter == "out":
        items = items.exclude(external_game_id__in=catalog_appids)

    if sort == "title":
        items = items.order_by("game_title")
    elif sort == "recent":
        items = items.order_by(models.F("last_played_at").desc(nulls_last=True), "game_title")
    else:
        sort = "playtime"
        items = items.order_by("-playtime_minutes", "game_title")

    page_obj = Paginator(items, STEAM_LIBRARY_PAGE_SIZE).get_page(request.GET.get("page"))
    page_items = attach_steam_apps(page_obj.object_list)
    page_appids = [item.external_game_id for item in page_items]

    games_by_appid = {g.steam_appid: g for g in Game.objects.filter(steam_appid__in=page_appids)}
    viewer_entries = {
        e.game_id: e
        for e in LibraryEntry.objects.filter(user=viewer, game__in=games_by_appid.values())
    }
    pending_appids = set(
        GameRequest.objects.filter(status="pending", steam_appid__in=page_appids)
        .values_list("steam_appid", flat=True)
    )

    for item in page_items:
        item.catalog_game = games_by_appid.get(item.external_game_id)
        entry = viewer_entries.get(item.catalog_game.id) if item.catalog_game else None
        item.viewer_entry = entry
        item.viewer_status_label = get_status_label(entry.status) if entry else None
        item.request_pending = item.external_game_id in pending_appids

    totals = all_items.aggregate(
        minutes=models.Sum("playtime_minutes"),
        last_synced=models.Max("synced_at"),
    )

    context = {
        "profile_user": owner,
        "is_own": is_own,
        "steam_account": steam_account,
        "items": page_items,
        "page_obj": page_obj,
        "query": query,
        "catalog_filter": catalog_filter,
        "selected_sort": sort,
        "games_count": all_items.count(),
        "in_catalog_count": all_items.filter(external_game_id__in=catalog_appids).count(),
        "total_hours": round((totals["minutes"] or 0) / 60),
        "last_synced_at": totals["last_synced"],
        "filtered_count": page_obj.paginator.count,
    }

    return render(request, "library/steam_library.html", context)


@library_login_required
def steam_library(request):
    user = request.library_user

    return _render_steam_library(request, user, user)


@library_login_required
def user_steam_library(request, user_id):
    viewer = request.library_user

    owner = get_object_or_404(User, id=user_id)

    if viewer.id == owner.id:
        return redirect("library:steam_library")

    if not can_view_profile(viewer, owner):
        return redirect("library:user_profile", owner.id)

    return _render_steam_library(request, viewer, owner)


@require_POST
@library_login_required
def steam_suggest_game(request, appid):
    """Створює заявку на додавання гри з власної Steam-бібліотеки до каталогу."""
    user = request.library_user

    item = get_object_or_404(
        ExternalLibraryItem, user=user, provider="steam", external_game_id=str(appid)
    )

    if Game.objects.filter(steam_appid=item.external_game_id).exists():
        messages.info(request, f'Гра "{item.game_title}" вже є в каталозі.')
    elif GameRequest.objects.filter(status="pending", steam_appid=item.external_game_id).exists():
        messages.info(request, f'Заявку на "{item.game_title}" вже подано, вона очікує модерації.')
    else:
        GameRequest.objects.create(
            user=user,
            title=item.game_title,
            description="",
            steam_appid=item.external_game_id,
            status="pending",
            created_at=timezone.now(),
        )
        messages.success(request, f'Заявку на додавання "{item.game_title}" до каталогу надіслано.')

    return redirect_to_next(request, "library:steam_library")


# --- Зіставлення каталогу зі Steam (адміністратор) ----------------------------

@admin_required
def admin_steam_matching(request):
    catalog_appids = set(
        Game.objects.exclude(steam_appid__isnull=True).exclude(steam_appid="")
        .values_list("steam_appid", flat=True)
    )

    # Унікальні ігри зі Steam-бібліотек усіх користувачів, яких ще немає в каталозі.
    steam_games = list(
        ExternalLibraryItem.objects
        .filter(provider="steam")
        .exclude(external_game_id__in=catalog_appids)
        .values("external_game_id")
        .annotate(
            title=models.Max("game_title"),
            owners=models.Count("user", distinct=True),
            minutes=models.Sum("playtime_minutes"),
        )
        .order_by("-owners", "-minutes")
    )

    by_title = {}
    for steam_game in steam_games:
        by_title.setdefault(normalize_title(steam_game["title"]), []).append(steam_game)

    unlinked_games = list(
        Game.objects.filter(models.Q(steam_appid__isnull=True) | models.Q(steam_appid=""))
        .order_by("title")
    )
    for game in unlinked_games:
        game.steam_candidates = by_title.get(normalize_title(game.title), [])

    return render(request, "library/admin_steam_matching.html", {
        "unlinked_games": unlinked_games,
        "popular_steam_games": steam_games[:20],
        "linked_count": len(catalog_appids),
    })


@require_POST
@admin_required
def admin_steam_link(request, game_id):
    game = get_object_or_404(Game, id=game_id)
    appid = request.POST.get("steam_appid", "").strip()

    if not is_valid_appid(appid):
        messages.error(request, "Steam AppID має складатися лише з цифр.")
    elif Game.objects.filter(steam_appid=appid).exclude(id=game.id).exists():
        other = Game.objects.get(steam_appid=appid)
        messages.error(request, f'AppID {appid} уже прив\'язаний до гри "{other.title}".')
    else:
        game.steam_appid = appid
        game.save(update_fields=["steam_appid"])
        added = link_game_to_steam_owners(game)
        messages.success(
            request,
            f'Гру "{game.title}" прив\'язано до Steam (appid {appid}). '
            f"Додано до бібліотек користувачів: {added}."
        )

    return redirect("library:admin_steam_matching")
