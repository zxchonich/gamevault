from django.shortcuts import render, get_object_or_404, redirect
from django.utils import timezone
from django.db import models, connection
from django.db.models import Avg
from .models import Game, Genre, Review, User, LibraryEntry, GameRequest, SocialConnection, Role, Recommendation, GameGenre
from django.contrib import messages
from django.core.paginator import Paginator
from django.contrib.auth.hashers import make_password, check_password


def home(request):
    current_user = get_current_user(request)

    games = (
        Game.objects
        .all()
        .annotate(avg_score=Avg('reviews__score'))
        .order_by('-created_at')[:6]
    )

    genres = Genre.objects.all().order_by('name')[:10]

    top_rated_games = (
        Game.objects
        .annotate(avg_score=Avg('reviews__score'))
        .filter(avg_score__isnull=False)
        .order_by('-avg_score', 'title')[:5]
    )

    most_added_games = (
        Game.objects
        .annotate(library_count=models.Count('library_entries'))
        .filter(library_count__gt=0)
        .order_by('-library_count', 'title')[:5]
    )

    active_users = (
    User.objects
    .annotate(
        library_count=models.Count('library_entries', distinct=True),
        review_count=models.Count('reviews', distinct=True),
        activity_score=(
            models.Count('library_entries', distinct=True) * 10 +
            models.Count('reviews', distinct=True) * 5
        )
    )
    .order_by('-activity_score', '-library_count', '-review_count', 'username')[:5]
    )

    total_games_count = Game.objects.count()
    total_genres_count = Genre.objects.count()
    total_users_count = User.objects.count()
    total_reviews_count = Review.objects.count()
    total_library_entries_count = LibraryEntry.objects.count()

    user_library_count = 0
    user_review_count = 0
    user_friends_count = 0

    if current_user is not None:
        user_library_count = LibraryEntry.objects.filter(user=current_user).count()
        user_review_count = Review.objects.filter(user=current_user).count()
        user_friends_count = SocialConnection.objects.filter(
            status='accepted'
        ).filter(
            models.Q(sender=current_user) | models.Q(receiver=current_user)
        ).count()

    games = attach_visible_genres_to_games(games)
    top_rated_games = attach_visible_genres_to_games(top_rated_games)
    most_added_games = attach_visible_genres_to_games(most_added_games)

    context = {
        'current_user': current_user,
        'games': games,
        'genres': genres,
        'top_rated_games': top_rated_games,
        'most_added_games': most_added_games,
        'active_users': active_users,
        'total_games_count': total_games_count,
        'total_genres_count': total_genres_count,
        'total_users_count': total_users_count,
        'total_reviews_count': total_reviews_count,
        'total_library_entries_count': total_library_entries_count,
        'user_library_count': user_library_count,
        'user_review_count': user_review_count,
        'user_friends_count': user_friends_count,
    }

    return render(request, 'library/home.html', context)

def game_list(request):
    query = request.GET.get('q', '')
    selected_genres = request.GET.getlist('genres')
    sort = request.GET.get('sort', 'title')

    games = Game.objects.all().annotate(avg_score=Avg('reviews__score'))
    genres = Genre.objects.all().order_by('name')

    if query:
        games = games.filter(title__icontains=query)

    if selected_genres:
        for genre_id in selected_genres:
            games = games.filter(game_genres__genre_id=genre_id)

    if sort == 'newest':
        games = games.order_by('-created_at')
    elif sort == 'rating':
        games = games.order_by('-avg_score', 'title')
    else:
        games = games.order_by('title')

    games = games.distinct()

    paginator = Paginator(games, 8)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    page_obj.object_list = attach_visible_genres_to_games(page_obj.object_list)

    total_games_count = Game.objects.count()
    games_with_reviews_count = Game.objects.filter(reviews__isnull=False).distinct().count()
    genres_count = Genre.objects.count()

    context = {
        'games': page_obj,
        'page_obj': page_obj,
        'genres': genres,
        'query': query,
        'selected_genres': selected_genres,
        'selected_sort': sort,
        'total_games_count': total_games_count,
        'games_with_reviews_count': games_with_reviews_count,
        'genres_count': genres_count,
    }

    return render(request, 'library/game_list.html', context)

def game_detail(request, game_id):
    game = get_object_or_404(Game, id=game_id)
    reviews = Review.objects.filter(game=game).order_by('-created_at')

    game_genres = (
        Genre.objects
        .filter(game_genres__game=game)
        .order_by('name')
    )

    average_score = reviews.aggregate(avg_score=Avg('score'))['avg_score']
    reviews_count = reviews.count()

    if average_score is None:
        average_score = 0

    user = get_current_user(request)
    library_entry = None
    user_review = None
    user_review_status = 'Не додана'

    if user is not None:
        library_entry = LibraryEntry.objects.filter(user=user, game=game).first()
        user_review = Review.objects.filter(user=user, game=game).first()

        if user_review:
            user_review_status = 'Додана'
    
    library_status_label = None

    if library_entry:
        library_status_label = get_status_label(library_entry.status)

    context = {
        'game': game,
        'reviews': reviews,
        'game_genres': game_genres,
        'library_entry': library_entry,
        'user_review': user_review,
        'average_score': average_score,
        'reviews_count': reviews_count,
        'user_review_status': user_review_status,
        'library_status_label': library_status_label,
    }

    return render(request, 'library/game_detail.html', context)

def get_current_user(request):
    user_id = request.session.get('library_user_id')

    if not user_id:
        return None

    return User.objects.filter(id=user_id).first()

def are_friends(user1, user2):
    return SocialConnection.objects.filter(
        status='accepted'
    ).filter(
        models.Q(sender=user1, receiver=user2) |
        models.Q(sender=user2, receiver=user1)
    ).exists()

def get_status_label(status):
    status_labels = {
        'planned': 'Планую',
        'playing': 'Граю',
        'completed': 'Пройдено',
        'paused': 'Відкладено',
        'dropped': 'Закинуто',
    }

    return status_labels.get(status, status)

def attach_visible_genres_to_games(games, limit=3):
    game_list = list(games)
    game_ids = [game.id for game in game_list]

    if not game_ids:
        return game_list

    genre_links = list(
        GameGenre.objects
        .filter(game_id__in=game_ids)
        .values('game_id', 'genre_id')
    )

    genre_ids = {item['genre_id'] for item in genre_links}

    genres_by_id = {
        genre.id: genre
        for genre in Genre.objects.filter(id__in=genre_ids).order_by('name')
    }

    genres_by_game = {}

    for item in genre_links:
        genre = genres_by_id.get(item['genre_id'])

        if genre is not None:
            genres_by_game.setdefault(item['game_id'], []).append(genre)

    for game in game_list:
        game.visible_genres = genres_by_game.get(game.id, [])[:limit]

    return game_list


def attach_visible_genres_to_entries(entries, limit=3):
    entry_list = list(entries)
    games = [entry.game for entry in entry_list]
    attach_visible_genres_to_games(games, limit)
    return entry_list


def attach_visible_genres_to_recommendations(recommendations, limit=3):
    recommendation_list = list(recommendations)
    games = [recommendation.game for recommendation in recommendation_list]
    attach_visible_genres_to_games(games, limit)
    return recommendation_list

def my_library(request):
    user = get_current_user(request)

    if user is None:
        return redirect('library:login')

    query = request.GET.get('q', '').strip()
    selected_status = request.GET.get('status', '')
    selected_genres = request.GET.getlist('genres')
    sort = request.GET.get('sort', 'newest')

    all_entries = (
        LibraryEntry.objects
        .filter(user=user)
        .select_related('game')
        .order_by('-added_at')
    )

    entries = all_entries

    if query:
        entries = entries.filter(game__title__icontains=query)

    if selected_status:
        entries = entries.filter(status=selected_status)

    if selected_genres:
        for genre_id in selected_genres:
            entries = entries.filter(game__game_genres__genre_id=genre_id)

    if sort == 'title':
        entries = entries.order_by('game__title')
    elif sort == 'oldest':
        entries = entries.order_by('added_at')
    else:
        entries = entries.order_by('-added_at')

    entries = entries.distinct()

    genres = Genre.objects.all().order_by('name')

    library_count = all_entries.count()
    planned_count = all_entries.filter(status='planned').count()
    playing_count = all_entries.filter(status='playing').count()
    completed_count = all_entries.filter(status='completed').count()
    paused_count = all_entries.filter(status='paused').count()
    dropped_count = all_entries.filter(status='dropped').count()
    filtered_count = entries.count()

    entries = list(entries)

    for entry in entries:
        entry.status_label = get_status_label(entry.status)

    entries = attach_visible_genres_to_entries(entries)

    status_choices = [
        {'value': 'planned', 'label': 'Планую'},
        {'value': 'playing', 'label': 'Граю'},
        {'value': 'completed', 'label': 'Пройдено'},
        {'value': 'paused', 'label': 'Відкладено'},
        {'value': 'dropped', 'label': 'Закинуто'},
    ]

    context = {
        'user': user,
        'entries': entries,
        'genres': genres,
        'status_choices': status_choices,

        'query': query,
        'selected_status': selected_status,
        'selected_genres': selected_genres,
        'selected_sort': sort,

        'library_count': library_count,
        'planned_count': planned_count,
        'playing_count': playing_count,
        'completed_count': completed_count,
        'paused_count': paused_count,
        'dropped_count': dropped_count,
        'filtered_count': filtered_count,
    }

    return render(request, 'library/my_library.html', context)

def add_to_library(request, game_id):
    user = get_current_user(request)

    if user is None:
        return redirect('library:login')

    game = get_object_or_404(Game, id=game_id)

    entry, created = LibraryEntry.objects.get_or_create(
        user=user,
        game=game,
        defaults={
            'status': 'planned',
            'added_at': timezone.now(),
        }
    )

    if created:
        messages.success(request, f'Гру "{game.title}" додано до бібліотеки.')
    else:
        messages.info(request, f'Гра "{game.title}" вже є у вашій бібліотеці.')

    return redirect('library:my_library')


def update_library_status(request, entry_id):
    user = get_current_user(request)

    if user is None:
        return redirect('library:login')

    entry = get_object_or_404(LibraryEntry, id=entry_id, user=user)

    if request.method == 'POST':
        new_status = request.POST.get('status')

        allowed_statuses = ['planned', 'playing', 'completed', 'paused', 'dropped']

        if new_status in allowed_statuses:
            entry.status = new_status
            entry.save()
            messages.success(request, f'Статус гри "{entry.game.title}" оновлено.')

    return redirect('library:my_library')

def add_review(request, game_id):
    user = get_current_user(request)

    if user is None:
        return redirect('library:login')

    game = get_object_or_404(Game, id=game_id)

    if request.method == 'POST':
        score = request.POST.get('score')
        text = request.POST.get('text', '').strip()

        try:
            score = int(score)
        except (TypeError, ValueError):
            score = None

        if score is not None and 1 <= score <= 10:
            review, created = Review.objects.get_or_create(
                user=user,
                game=game,
                defaults={
                    'score': score,
                    'text': text,
                    'created_at': timezone.now(),
                }
            )

            if created:
                messages.success(request, 'Рецензію додано.')
            else:
                review.score = score
                review.text = text
                review.updated_at = timezone.now()
                review.save()
                messages.success(request, 'Рецензію оновлено.')
        else:
            messages.error(request, 'Оцінка має бути від 1 до 10.')

    return redirect('library:game_detail', game_id=game.id)

def request_game(request):
    user = get_current_user(request)

    if user is None:
        return redirect('library:login')

    if request.method == 'POST':
        title = request.POST.get('title', '').strip()
        description = request.POST.get('description', '').strip()

        if title:
            GameRequest.objects.create(
                user=user,
                title=title,
                description=description,
                status='pending',
                created_at=timezone.now(),
            )

            messages.success(request, 'Заявку на додавання гри надіслано.')
            return redirect('library:my_requests')
        else:
            messages.error(request, 'Вкажіть назву гри.')

    return render(request, 'library/request_game.html', {
        'user': user,
    })

def recommendations(request):
    user = get_current_user(request)

    if user is None:
        return redirect('library:login')

    # Ігри, які вже є в бібліотеці користувача
    user_game_ids = set(
        LibraryEntry.objects
        .filter(user=user)
        .values_list('game_id', flat=True)
    )

    # Жанри ігор із бібліотеки користувача
    user_genre_ids = set(
        Genre.objects
        .filter(game_genres__game_id__in=user_game_ids)
        .values_list('id', flat=True)
    )

    # Ігри, які користувач оцінив високо
    high_rated_game_ids = set(
        Review.objects
        .filter(user=user, score__gte=8)
        .values_list('game_id', flat=True)
    )

    # Жанри високо оцінених ігор
    high_rated_genre_ids = set(
        Genre.objects
        .filter(game_genres__game_id__in=high_rated_game_ids)
        .values_list('id', flat=True)
    )

    # Знаходимо друзів користувача
    accepted_connections = SocialConnection.objects.filter(
        status='accepted'
    ).filter(
        models.Q(sender=user) | models.Q(receiver=user)
    )

    friend_ids = []

    for connection in accepted_connections:
        if connection.sender_id == user.id:
            friend_ids.append(connection.receiver_id)
        else:
            friend_ids.append(connection.sender_id)

    # Ігри, які є в бібліотеках друзів
    friend_game_ids = set(
        LibraryEntry.objects
        .filter(user_id__in=friend_ids)
        .values_list('game_id', flat=True)
    )

    # Ігри, які друзі високо оцінили
    friend_high_rated_game_ids = set(
        Review.objects
        .filter(user_id__in=friend_ids, score__gte=8)
        .values_list('game_id', flat=True)
    )

    # Кандидати: усі ігри, яких ще немає у бібліотеці користувача
    candidate_games = (
        Game.objects
        .exclude(id__in=user_game_ids)
        .annotate(avg_score=Avg('reviews__score'))
        .order_by('title')
    )

    # Очищаємо старі рекомендації користувача
    Recommendation.objects.filter(user=user).delete()

    recommended_games = []

    for game in candidate_games:
        score = 0
        reasons = []

        game_genre_ids = set(
            Genre.objects
            .filter(game_genres__game=game)
            .values_list('id', flat=True)
        )

        # 1. Збіг жанрів із бібліотекою користувача
        common_user_genres = game_genre_ids.intersection(user_genre_ids)

        if common_user_genres:
            score += 20
            reasons.append('збіг із жанрами ігор у вашій бібліотеці')

        # 2. Збіг із жанрами високо оцінених ігор
        common_high_rated_genres = game_genre_ids.intersection(high_rated_genre_ids)

        if common_high_rated_genres:
            score += 30
            reasons.append('схожість із жанрами ігор, які ви високо оцінили')

        # 3. Гра є в бібліотеці друга
        if game.id in friend_game_ids:
            score += 20
            reasons.append('гра є в бібліотеці ваших друзів')

        # 4. Друг високо оцінив гру
        if game.id in friend_high_rated_game_ids:
            score += 20
            reasons.append('цю гру високо оцінили ваші друзі')

        # 5. Висока середня оцінка
        if game.avg_score is not None:
            if game.avg_score >= 8:
                score += 10
                reasons.append('гра має високу середню оцінку')
            elif game.avg_score >= 6:
                score += 5
                reasons.append('гра має непогану середню оцінку')

        # Обмежуємо максимум 100
        if score > 100:
            score = 100

        # Якщо немає причин, не рекомендуємо
        if score > 0:
            reason_text = '; '.join(reasons)

            recommendation = Recommendation.objects.create(
                user=user,
                game=game,
                match_score=score,
                reason=reason_text,
                created_at=timezone.now(),
            )

            recommended_games.append(recommendation)

    recommendations_list = (
    Recommendation.objects
    .filter(user=user)
    .select_related('game')
    .order_by('-match_score', '-created_at')
    )

    recommendations_count = recommendations_list.count()

    best_match = recommendations_list.first()

    if best_match:
        best_match_score = best_match.match_score
    else:
        best_match_score = 0

    average_match = recommendations_list.aggregate(
        average_score=Avg('match_score')
    )['average_score']

    if average_match is None:
        average_match = 0

    recommendations_for_template = attach_visible_genres_to_recommendations(recommendations_list)

    context = {
        'user': user,
        'recommendations': recommendations_for_template,
        'recommendations_count': recommendations_count,
        'best_match_score': best_match_score,
        'average_match': average_match,
    }

    return render(request, 'library/recommendations.html', context)

def user_list(request):
    current_user = get_current_user(request)

    if current_user is None:
        return redirect('library:login')

    users = User.objects.exclude(id=current_user.id).order_by('username')

    connections = SocialConnection.objects.filter(
        models.Q(sender=current_user) | models.Q(receiver=current_user)
    )

    connection_map = {}

    for connection in connections:
        if connection.sender_id == current_user.id:
            other_user_id = connection.receiver_id
        else:
            other_user_id = connection.sender_id

        connection_map[other_user_id] = connection.status

    users_data = []

    for user in users:
        users_data.append({
            'user': user,
            'connection_status': connection_map.get(user.id),
        })

    context = {
        'current_user': current_user,
        'users_data': users_data,
    }

    return render(request, 'library/user_list.html', context)

def add_friend(request, user_id):
    current_user = get_current_user(request)
    target_user = get_object_or_404(User, id=user_id)

    if current_user is None or current_user.id == target_user.id:
        return redirect('library:user_list')

    existing_connection = SocialConnection.objects.filter(
        sender=current_user,
        receiver=target_user
    ).first()

    reverse_connection = SocialConnection.objects.filter(
        sender=target_user,
        receiver=current_user
    ).first()

    if existing_connection is None and reverse_connection is None:
        SocialConnection.objects.create(
            sender=current_user,
            receiver=target_user,
            status='pending',
            created_at=timezone.now()
        )
        messages.success(request, f'Заявку в друзі для {target_user.username} надіслано.')
    else:
        messages.info(request, 'Заявка або зв’язок з цим користувачем уже існує.')

    return redirect('library:friends')


def friends(request):
    current_user = get_current_user(request)

    if current_user is None:
        return redirect('library:login')

    sent_requests = SocialConnection.objects.filter(
        sender=current_user,
        status='pending'
    ).select_related('receiver')

    received_requests = SocialConnection.objects.filter(
        receiver=current_user,
        status='pending'
    ).select_related('sender')

    accepted_connections = SocialConnection.objects.filter(
        status='accepted'
    ).filter(
        models.Q(sender=current_user) | models.Q(receiver=current_user)
    ).select_related('sender', 'receiver')

    connections = SocialConnection.objects.filter(
        models.Q(sender=current_user) | models.Q(receiver=current_user)
    )

    connected_user_ids = set()

    for connection in connections:
        if connection.sender_id == current_user.id:
            connected_user_ids.add(connection.receiver_id)
        else:
            connected_user_ids.add(connection.sender_id)

    friend_ids = set()

    for connection in accepted_connections:
        if connection.sender_id == current_user.id:
            friend_ids.add(connection.receiver_id)
        else:
            friend_ids.add(connection.sender_id)

    friends_of_friends_connections = SocialConnection.objects.filter(
        status='accepted'
    ).filter(
        models.Q(sender_id__in=friend_ids) | models.Q(receiver_id__in=friend_ids)
    )

    friends_of_friends_ids = set()

    for connection in friends_of_friends_connections:
        if connection.sender_id in friend_ids:
            candidate_id = connection.receiver_id
        else:
            candidate_id = connection.sender_id

        if candidate_id != current_user.id and candidate_id not in connected_user_ids:
            friends_of_friends_ids.add(candidate_id)

    suggested_users_from_friends = User.objects.filter(
        id__in=friends_of_friends_ids
    ).order_by('username')

    suggested_users_count = suggested_users_from_friends.count()

    extra_suggested_users = User.objects.none()

    if suggested_users_count < 3:
        extra_suggested_users = (
            User.objects
            .exclude(id=current_user.id)
            .exclude(id__in=connected_user_ids)
            .exclude(id__in=friends_of_friends_ids)
            .order_by('username')[:3 - suggested_users_count]
        )

    suggested_users = list(suggested_users_from_friends[:3]) + list(extra_suggested_users)

    context = {
    'current_user': current_user,
    'sent_requests': sent_requests,
    'received_requests': received_requests,
    'accepted_connections': accepted_connections,
    'suggested_users': suggested_users,
    'friends_count': accepted_connections.count(),
    'received_requests_count': received_requests.count(),
    'sent_requests_count': sent_requests.count(),
    }

    return render(request, 'library/friends.html', context)


def accept_connection(request, connection_id):
    current_user = get_current_user(request)
    connection = get_object_or_404(SocialConnection, id=connection_id)

    if current_user is not None and connection.receiver_id == current_user.id:
        connection.status = 'accepted'
        connection.save()
        messages.success(request, 'Заявку в друзі прийнято.')

    return redirect('library:friends')


def reject_connection(request, connection_id):
    current_user = get_current_user(request)
    connection = get_object_or_404(SocialConnection, id=connection_id)

    if current_user is not None and connection.receiver_id == current_user.id:
        connection.status = 'rejected'
        connection.save()
        messages.success(request, 'Заявку в друзі відхилено.')

    return redirect('library:friends')

def delete_connection(request, connection_id):
    current_user = get_current_user(request)

    if current_user is None:
        return redirect('library:login')

    connection = get_object_or_404(SocialConnection, id=connection_id)

    if connection.sender_id != current_user.id and connection.receiver_id != current_user.id:
        return render(request, 'library/no_access.html')

    if request.method == 'POST':
        if connection.sender_id == current_user.id:
            other_user = connection.receiver
        else:
            other_user = connection.sender

        connection.delete()

        messages.success(
            request,
            f'Користувача {other_user.username} видалено з друзів.'
        )

    return redirect('library:friends')

def user_library(request, user_id):
    current_user = get_current_user(request)

    if current_user is None:
        return redirect('library:login')

    profile_user = get_object_or_404(User, id=user_id)

    if current_user.id == profile_user.id:
        return redirect('library:my_library')

    connection = SocialConnection.objects.filter(
        models.Q(sender=current_user, receiver=profile_user) |
        models.Q(sender=profile_user, receiver=current_user)
    ).first()

    if profile_user.is_private and not are_friends(current_user, profile_user):
        library_count = LibraryEntry.objects.filter(user=profile_user).count()

        return render(request, 'library/private_profile.html', {
            'current_user': current_user,
            'profile_user': profile_user,
            'connection': connection,
            'library_count': library_count,
        })

    query = request.GET.get('q', '').strip()
    selected_status = request.GET.get('status', '')
    selected_genres = request.GET.getlist('genres')
    sort = request.GET.get('sort', 'newest')

    all_entries = (
        LibraryEntry.objects
        .filter(user=profile_user)
        .select_related('game')
        .order_by('-added_at')
    )

    entries = all_entries

    if query:
        entries = entries.filter(game__title__icontains=query)

    if selected_status:
        entries = entries.filter(status=selected_status)

    if selected_genres:
        for genre_id in selected_genres:
            entries = entries.filter(game__game_genres__genre_id=genre_id)

    if sort == 'title':
        entries = entries.order_by('game__title')
    elif sort == 'oldest':
        entries = entries.order_by('added_at')
    else:
        entries = entries.order_by('-added_at')

    entries = entries.distinct()

    genres = Genre.objects.all().order_by('name')

    library_count = all_entries.count()
    planned_count = all_entries.filter(status='planned').count()
    playing_count = all_entries.filter(status='playing').count()
    completed_count = all_entries.filter(status='completed').count()
    paused_count = all_entries.filter(status='paused').count()
    dropped_count = all_entries.filter(status='dropped').count()
    filtered_count = entries.count()

    entries = list(entries)

    for entry in entries:
        entry.status_label = get_status_label(entry.status)

    entries = attach_visible_genres_to_entries(entries)

    status_choices = [
        {'value': 'planned', 'label': 'Планує'},
        {'value': 'playing', 'label': 'Грає'},
        {'value': 'completed', 'label': 'Пройдено'},
        {'value': 'paused', 'label': 'Відкладено'},
        {'value': 'dropped', 'label': 'Закинуто'},
    ]

    context = {
        'current_user': current_user,
        'profile_user': profile_user,
        'entries': entries,
        'genres': genres,
        'status_choices': status_choices,
        'connection': connection,

        'query': query,
        'selected_status': selected_status,
        'selected_genres': selected_genres,
        'selected_sort': sort,

        'library_count': library_count,
        'planned_count': planned_count,
        'playing_count': playing_count,
        'completed_count': completed_count,
        'paused_count': paused_count,
        'dropped_count': dropped_count,
        'filtered_count': filtered_count,
    }

    return render(request, 'library/user_library.html', context)

def login_view(request):
    error = None

    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '').strip()

        user = User.objects.filter(username=username).first()

        if user and check_password(password, user.password_hash):
            request.session['library_user_id'] = user.id
            return redirect('library:home')

        elif user and password == user.password_hash:
            user.password_hash = make_password(password)
            user.save(update_fields=['password_hash'])

            request.session['library_user_id'] = user.id
            return redirect('library:home')

        else:
            error = 'Неправильний логін або пароль.'

    return render(request, 'library/login.html', {
        'error': error,
    })


def logout_view(request):
    request.session.pop('library_user_id', None)
    return redirect('library:home')

def profile(request):
    user = get_current_user(request)

    if user is None:
        return redirect('library:login')

    entries = (
        LibraryEntry.objects
        .filter(user=user)
        .select_related('game')
        .order_by('-added_at')
    )

    reviews = (
        Review.objects
        .filter(user=user)
        .select_related('game')
        .order_by('-created_at')
    )

    library_count = entries.count()
    review_count = reviews.count()

    friends_count = SocialConnection.objects.filter(
        status='accepted'
    ).filter(
        models.Q(sender=user) | models.Q(receiver=user)
    ).count()

    planned_count = entries.filter(status='planned').count()
    playing_count = entries.filter(status='playing').count()
    completed_count = entries.filter(status='completed').count()
    paused_count = entries.filter(status='paused').count()
    dropped_count = entries.filter(status='dropped').count()

    if library_count > 0:
        completed_percent = int((completed_count / library_count) * 100)
        playing_percent = int((playing_count / library_count) * 100)
        planned_percent = int((planned_count / library_count) * 100)
        paused_percent = int((paused_count / library_count) * 100)
        dropped_percent = int((dropped_count / library_count) * 100)
    else:
        completed_percent = 0
        playing_percent = 0
        planned_percent = 0
        paused_percent = 0
        dropped_percent = 0

    average_score = reviews.aggregate(avg_score=Avg('score'))['avg_score']

    if average_score is None:
        average_score = 0

    recent_entries = entries[:4]
    recent_reviews = reviews[:3]

    context = {
        'user': user,
        'profile_user': user,
        'is_own_profile': True,

        'library_count': library_count,
        'review_count': review_count,
        'friends_count': friends_count,

        'planned_count': planned_count,
        'playing_count': playing_count,
        'completed_count': completed_count,
        'paused_count': paused_count,
        'dropped_count': dropped_count,

        'completed_percent': completed_percent,
        'playing_percent': playing_percent,
        'planned_percent': planned_percent,
        'paused_percent': paused_percent,
        'dropped_percent': dropped_percent,

        'average_score': average_score,

        'recent_entries': recent_entries,
        'recent_reviews': recent_reviews,
    }

    return render(request, 'library/profile.html', context)

def user_profile(request, user_id):
    current_user = get_current_user(request)

    if current_user is None:
        return redirect('library:login')

    profile_user = get_object_or_404(User, id=user_id)

    if current_user.id == profile_user.id:
        return redirect('library:profile')

    connection = SocialConnection.objects.filter(
        models.Q(sender=current_user, receiver=profile_user) |
        models.Q(sender=profile_user, receiver=current_user)
    ).first()

    if profile_user.is_private and not are_friends(current_user, profile_user):
        library_count = LibraryEntry.objects.filter(user=profile_user).count()

        return render(request, 'library/private_profile.html', {
            'current_user': current_user,
            'profile_user': profile_user,
            'connection': connection,
            'library_count': library_count,
        })

    entries = (
        LibraryEntry.objects
        .filter(user=profile_user)
        .select_related('game')
        .order_by('-added_at')
    )

    reviews = (
        Review.objects
        .filter(user=profile_user)
        .select_related('game')
        .order_by('-created_at')
    )

    library_count = entries.count()
    review_count = reviews.count()

    friends_count = SocialConnection.objects.filter(
        status='accepted'
    ).filter(
        models.Q(sender=profile_user) | models.Q(receiver=profile_user)
    ).count()

    planned_count = entries.filter(status='planned').count()
    playing_count = entries.filter(status='playing').count()
    completed_count = entries.filter(status='completed').count()
    paused_count = entries.filter(status='paused').count()
    dropped_count = entries.filter(status='dropped').count()

    if library_count > 0:
        completed_percent = int((completed_count / library_count) * 100)
        playing_percent = int((playing_count / library_count) * 100)
        planned_percent = int((planned_count / library_count) * 100)
        paused_percent = int((paused_count / library_count) * 100)
        dropped_percent = int((dropped_count / library_count) * 100)
    else:
        completed_percent = 0
        playing_percent = 0
        planned_percent = 0
        paused_percent = 0
        dropped_percent = 0

    average_score = reviews.aggregate(avg_score=Avg('score'))['avg_score']

    if average_score is None:
        average_score = 0

    recent_entries = entries[:4]
    recent_reviews = reviews[:3]

    context = {
        'current_user': current_user,
        'profile_user': profile_user,
        'connection': connection,

        'library_count': library_count,
        'review_count': review_count,
        'friends_count': friends_count,

        'planned_count': planned_count,
        'playing_count': playing_count,
        'completed_count': completed_count,
        'paused_count': paused_count,
        'dropped_count': dropped_count,

        'completed_percent': completed_percent,
        'playing_percent': playing_percent,
        'planned_percent': planned_percent,
        'paused_percent': paused_percent,
        'dropped_percent': dropped_percent,

        'average_score': average_score,

        'recent_entries': recent_entries,
        'recent_reviews': recent_reviews,
    }

    return render(request, 'library/user_profile.html', context)

def is_admin_user(user):
    return user is not None and user.role is not None and user.role.name == 'admin'

def add_game_genres(game_id, genre_ids):
    with connection.cursor() as cursor:
        for genre_id in genre_ids:
            cursor.execute(
                """
                INSERT IGNORE INTO game_genres (game_id, genre_id)
                VALUES (%s, %s)
                """,
                [game_id, genre_id]
            )

def moderation(request):
    user = get_current_user(request)

    if user is None:
        return redirect('library:login')

    if not is_admin_user(user):
        return render(request, 'library/no_access.html')

    pending_requests = GameRequest.objects.filter(status='pending').select_related('user').order_by('-created_at')
    approved_requests = GameRequest.objects.filter(status='approved').select_related('user', 'moderator').order_by('-created_at')[:10]
    rejected_requests = GameRequest.objects.filter(status='rejected').select_related('user', 'moderator').order_by('-created_at')[:10]
    genres = Genre.objects.all().order_by('name')

    context = {
        'pending_requests': pending_requests,
        'approved_requests': approved_requests,
        'rejected_requests': rejected_requests,
        'genres': genres,
    }

    return render(request, 'library/moderation.html', context)


def approve_request(request, request_id):
    user = get_current_user(request)

    if user is None:
        return redirect('library:login')

    if not is_admin_user(user):
        return render(request, 'library/no_access.html')

    game_request = get_object_or_404(GameRequest, id=request_id)

    if game_request.status == 'pending':
        selected_genres = request.POST.getlist('genres')

        game = Game.objects.create(
            title=game_request.title,
            description=game_request.description,
            developer=None,
            release_date=None,
            created_at=timezone.now(),
        )

        if selected_genres:
            add_game_genres(game.id, selected_genres)

        game_request.status = 'approved'
        game_request.moderator = user
        game_request.reviewed_at = timezone.now()
        game_request.save()

        messages.success(request, f'Заявку "{game_request.title}" схвалено. Гру додано до каталогу.')

    return redirect('library:moderation')


def reject_request(request, request_id):
    user = get_current_user(request)

    if user is None:
        return redirect('library:login')

    if not is_admin_user(user):
        return render(request, 'library/no_access.html')

    game_request = get_object_or_404(GameRequest, id=request_id)

    if game_request.status == 'pending':
        game_request.status = 'rejected'
        game_request.moderator = user
        game_request.reviewed_at = timezone.now()
        game_request.save()
        messages.success(request, f'Заявку "{game_request.title}" відхилено.')

    return redirect('library:moderation')

def register_view(request):
    error = None

    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        email = request.POST.get('email', '').strip()
        password = request.POST.get('password', '').strip()
        password_confirm = request.POST.get('password_confirm', '').strip()

        if not username or not email or not password:
            error = 'Заповніть усі обов’язкові поля.'
        elif password != password_confirm:
            error = 'Паролі не збігаються.'
        elif User.objects.filter(username=username).exists():
            error = 'Користувач із таким логіном уже існує.'
        elif User.objects.filter(email=email).exists():
            error = 'Користувач із такою електронною адресою вже існує.'
        else:
            role = None

            try:
                role = Role.objects.get(name='user')
            except Role.DoesNotExist:
                error = 'У базі даних немає ролі user. Додайте її через адмінку.'

            if role is not None:
                user = User.objects.create(
                    role=role,
                    username=username,
                    email=email,
                    password_hash=make_password(password),
                    created_at=timezone.now(),
                )

                request.session['library_user_id'] = user.id
                return redirect('library:profile')

    return render(request, 'library/register.html', {
        'error': error,
    })

def delete_library_entry(request, entry_id):
    user = get_current_user(request)

    if user is None:
        return redirect('library:login')

    entry = get_object_or_404(LibraryEntry, id=entry_id, user=user)
    game_title = entry.game.title

    if request.method == 'POST':
        Review.objects.filter(user=user, game=entry.game).delete()

        entry.delete()

        messages.success(
            request,
            f'Гру "{game_title}" видалено з бібліотеки. Рецензію до цієї гри також видалено.'
        )

    return redirect('library:my_library')

def my_requests(request):
    user = get_current_user(request)

    if user is None:
        return redirect('library:login')

    requests = (
        GameRequest.objects
        .filter(user=user)
        .select_related('moderator')
        .order_by('-created_at')
    )

    total_requests_count = requests.count()
    pending_requests_count = requests.filter(status='pending').count()
    approved_requests_count = requests.filter(status='approved').count()

    context = {
        'requests': requests,
        'total_requests_count': total_requests_count,
        'pending_requests_count': pending_requests_count,
        'approved_requests_count': approved_requests_count,
    }

    return render(request, 'library/my_requests.html', context)

def my_reviews(request):
    user = get_current_user(request)

    if user is None:
        return redirect('library:login')

    reviews = (
        Review.objects
        .filter(user=user)
        .select_related('game')
        .order_by('-created_at')
    )

    context = {
        'reviews': reviews,
    }

    return render(request, 'library/my_reviews.html', context)

def edit_profile(request):
    user = get_current_user(request)

    if user is None:
        return redirect('library:login')

    error = None

    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        email = request.POST.get('email', '').strip()
        password = request.POST.get('password', '').strip()
        password_confirm = request.POST.get('password_confirm', '').strip()
        avatar = request.FILES.get('avatar')
        is_private = request.POST.get('is_private') == 'on'

        if not username or not email:
            error = 'Логін та email не можуть бути порожніми.'
        elif User.objects.filter(username=username).exclude(id=user.id).exists():
            error = 'Користувач із таким логіном уже існує.'
        elif User.objects.filter(email=email).exclude(id=user.id).exists():
            error = 'Користувач із таким email уже існує.'
        elif password and password != password_confirm:
            error = 'Паролі не збігаються.'
        else:
            user.username = username
            user.email = email
            user.is_private = is_private

            if password:
                user.password_hash = make_password(password)

            if avatar:
                user.avatar = avatar

            user.save()

            messages.success(request, 'Профіль успішно оновлено.')
            return redirect('library:profile')

    context = {
        'user': user,
        'error': error,
    }

    return render(request, 'library/edit_profile.html', context)
def admin_game_add(request):
    user = get_current_user(request)

    if not is_admin_user(user):
        return render(request, 'library/no_access.html')

    genres = Genre.objects.all().order_by('name')

    if request.method == 'POST':
        title = request.POST.get('title')
        description = request.POST.get('description')
        developer = request.POST.get('developer')
        release_date = request.POST.get('release_date')
        selected_genres = request.POST.getlist('genres')
        poster = request.FILES.get('poster')

        if not title:
            messages.error(request, 'Назва гри обов’язкова.')
            return redirect('library:admin_game_add')

        game = Game(
            title=title,
            description=description,
            developer=developer,
            created_at=timezone.now()
        )

        if release_date:
            game.release_date = release_date

        if poster:
            game.poster = poster

        game.save()

        for genre_id in selected_genres:
            GameGenre.objects.create(
                game=game,
                genre_id=genre_id
            )

        messages.success(request, 'Гру додано до каталогу.')
        return redirect('library:game_detail', game_id=game.id)

    context = {
        'genres': genres,
        'form_title': 'Додати гру',
        'button_text': 'Додати гру',
    }

    return render(request, 'library/admin_game_form.html', context)


def admin_game_edit(request, game_id):
    user = get_current_user(request)

    if not is_admin_user(user):
        return render(request, 'library/no_access.html')

    game = get_object_or_404(Game, id=game_id)
    genres = Genre.objects.all().order_by('name')

    selected_genre_ids = set(
        GameGenre.objects
        .filter(game=game)
        .values_list('genre_id', flat=True)
    )

    if request.method == 'POST':
        game.title = request.POST.get('title')
        game.description = request.POST.get('description')
        game.developer = request.POST.get('developer')

        release_date = request.POST.get('release_date')
        if release_date:
            game.release_date = release_date
        else:
            game.release_date = None

        poster = request.FILES.get('poster')
        if poster:
            game.poster = poster

        game.save()

        selected_genres = request.POST.getlist('genres')

        GameGenre.objects.filter(game=game).delete()

        for genre_id in selected_genres:
            GameGenre.objects.create(
                game=game,
                genre_id=genre_id
            )

        messages.success(request, 'Гру оновлено.')
        return redirect('library:game_detail', game_id=game.id)

    context = {
        'game': game,
        'genres': genres,
        'selected_genre_ids': selected_genre_ids,
        'form_title': 'Редагувати гру',
        'button_text': 'Зберегти зміни',
    }

    return render(request, 'library/admin_game_form.html', context)


def admin_game_delete(request, game_id):
    user = get_current_user(request)

    if not is_admin_user(user):
        return render(request, 'library/no_access.html')

    game = get_object_or_404(Game, id=game_id)

    if request.method == 'POST':
        GameGenre.objects.filter(game=game).delete()
        LibraryEntry.objects.filter(game=game).delete()
        Review.objects.filter(game=game).delete()
        Recommendation.objects.filter(game=game).delete()

        game.delete()

        messages.success(request, 'Гру видалено з каталогу.')
        return redirect('library:game_list')

    return redirect('library:game_detail', game_id=game.id)


def admin_review_delete(request, review_id):
    user = get_current_user(request)

    if user is None:
        return redirect('library:login')

    review = get_object_or_404(Review, id=review_id)
    game_id = review.game.id

    is_owner = review.user_id == user.id
    is_admin = is_admin_user(user)

    if not is_owner and not is_admin:
        messages.error(request, 'Ви не можете видалити цю рецензію.')
        return redirect('library:game_detail', game_id=game_id)

    if request.method == 'POST':
        review.delete()
        messages.success(request, 'Рецензію видалено.')

        next_url = request.POST.get('next')
        if next_url:
            return redirect(next_url)

        return redirect('library:game_detail', game_id=game_id)

    return redirect('library:game_detail', game_id=game_id)

def admin_genre_list(request):
    user = get_current_user(request)

    if not is_admin_user(user):
        return render(request, 'library/no_access.html')

    if request.method == 'POST':
        name = request.POST.get('name', '').strip()

        if not name:
            messages.error(request, 'Назва жанру не може бути порожньою.')
            return redirect('library:admin_genre_list')

        if Genre.objects.filter(name__iexact=name).exists():
            messages.error(request, 'Такий жанр уже існує.')
            return redirect('library:admin_genre_list')

        Genre.objects.create(name=name)

        messages.success(request, f'Жанр "{name}" додано.')
        return redirect('library:admin_genre_list')

    genres = Genre.objects.all().order_by('name')

    genre_usage = {}

    for genre in genres:
        genre_usage[genre.id] = GameGenre.objects.filter(genre_id=genre.id).count()

    genres_data = []

    for genre in genres:
        genres_data.append({
            'genre': genre,
            'games_count': genre_usage.get(genre.id, 0),
        })

    context = {
        'genres_data': genres_data,
        'genres_count': genres.count(),
    }

    return render(request, 'library/admin_genre_list.html', context)


def admin_genre_delete(request, genre_id):
    user = get_current_user(request)

    if not is_admin_user(user):
        return render(request, 'library/no_access.html')

    genre = get_object_or_404(Genre, id=genre_id)

    if request.method == 'POST':
        games_count = GameGenre.objects.filter(genre=genre).count()

        if games_count > 0:
            messages.error(
                request,
                f'Жанр "{genre.name}" не можна видалити, бо він використовується в іграх.'
            )
        else:
            genre_name = genre.name
            genre.delete()
            messages.success(request, f'Жанр "{genre_name}" видалено.')

    return redirect('library:admin_genre_list')