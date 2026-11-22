"""Представлення інтеграції зі Steam: підключення, синхронізація, Steam-бібліотека,
пропозиції ігор у каталог і зіставлення каталогу зі Steam для адміністратора."""

from django.contrib import messages
from django.core.paginator import Paginator
from django.db import models
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .models import ExternalAccount, ExternalLibraryItem, Game, GameRequest, LibraryEntry, User
from .services.steam_service import (
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
from .views import can_view_profile, get_current_user, get_status_label, is_admin_user

STEAM_LIBRARY_PAGE_SIZE = 24


def _redirect_back(request, fallback, *args):
    next_url = request.POST.get("next") or request.GET.get("next")
    if next_url and url_has_allowed_host_and_scheme(
        next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return redirect(next_url)
    return redirect(fallback, *args)


def _sync_and_report(request, user, steam_account):
    try:
        result = sync_steam_library(user, steam_account)
    except SteamError as exc:
        messages.error(request, str(exc))
        return

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
    user = get_current_user(request)

    if user is None:
        return redirect("library:login")

    return redirect(build_steam_login_url(request))


def steam_callback(request):
    user = get_current_user(request)

    if user is None:
        return redirect("library:login")

    if not validate_steam_openid_response(request):
        messages.error(request, "Не вдалося підтвердити вхід через Steam. Спробуйте ще раз.")
        return redirect("library:profile")

    steam_id = extract_steam_id_from_openid(request)

    if not steam_id:
        messages.error(request, "Steam повернув некоректний ідентифікатор акаунта.")
        return redirect("library:profile")

    linked_to_other_user = (
        ExternalAccount.objects
        .filter(provider="steam", external_user_id=steam_id)
        .exclude(user=user)
        .exists()
    )

    if linked_to_other_user:
        messages.error(request, "Цей Steam-акаунт уже прив'язаний до іншого користувача GameVault.")
        return redirect("library:profile")

    steam_profile = get_steam_profile(steam_id)

    steam_account, _ = ExternalAccount.objects.update_or_create(
        user=user,
        provider="steam",
        defaults={
            "external_user_id": steam_id,
            "username": steam_profile["username"] if steam_profile else f"Steam user {steam_id}",
            "profile_url": steam_profile["profile_url"] if steam_profile else f"https://steamcommunity.com/profiles/{steam_id}",
            "avatar_url": steam_profile["avatar_url"] if steam_profile else None,
        }
    )

    messages.success(request, "Steam-акаунт підключено.")

    # Одразу імпортуємо ігри, щоб не треба було окремо натискати "Синхронізувати".
    _sync_and_report(request, user, steam_account)

    return redirect("library:steam_library")


@require_POST
def steam_disconnect(request):
    user = get_current_user(request)

    if user is None:
        return redirect("library:login")

    # Імпортовані ігри Steam (external_library_items) видаляються каскадно;
    # записи в бібліотеці GameVault залишаються.
    ExternalAccount.objects.filter(user=user, provider="steam").delete()

    messages.success(request, "Steam-акаунт відв'язано.")
    return redirect("library:profile")


@require_POST
def steam_sync_library(request):
    user = get_current_user(request)

    if user is None:
        return redirect("library:login")

    steam_account = ExternalAccount.objects.filter(user=user, provider="steam").first()

    if not steam_account:
        messages.error(request, "Спочатку підключіть Steam-акаунт.")
        return redirect("library:profile")

    _sync_and_report(request, user, steam_account)
    return _redirect_back(request, "library:profile")


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


def steam_library(request):
    user = get_current_user(request)

    if user is None:
        return redirect("library:login")

    return _render_steam_library(request, user, user)


def user_steam_library(request, user_id):
    viewer = get_current_user(request)

    if viewer is None:
        return redirect("library:login")

    owner = get_object_or_404(User, id=user_id)

    if viewer.id == owner.id:
        return redirect("library:steam_library")

    if not can_view_profile(viewer, owner):
        return redirect("library:user_profile", owner.id)

    return _render_steam_library(request, viewer, owner)


@require_POST
def steam_suggest_game(request, appid):
    """Створює заявку на додавання гри з власної Steam-бібліотеки до каталогу."""
    user = get_current_user(request)

    if user is None:
        return redirect("library:login")

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

    return _redirect_back(request, "library:steam_library")


# --- Зіставлення каталогу зі Steam (адміністратор) ----------------------------

def admin_steam_matching(request):
    user = get_current_user(request)

    if user is None:
        return redirect("library:login")

    if not is_admin_user(user):
        return render(request, "library/no_access.html")

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
def admin_steam_link(request, game_id):
    user = get_current_user(request)

    if not is_admin_user(user):
        return render(request, "library/no_access.html")

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
