# CLAUDE.md

Этот файл содержит инструкции для Claude Code (claude.ai/code) по работе с кодом в этом репозитории.

## Проект

GameVault — курсовой проект на Django: веб-приложение для агрегации персональных игровых библиотек. Каталог игр с поиском и фильтрацией, личная библиотека со статусами прохождения, рецензии и оценки, профили пользователей, друзья и заявки в друзья, персональные рекомендации, заявки на добавление игр с модерацией, админ-управление играми и жанрами, синхронизация библиотеки Steam. Тексты интерфейса и комментарии в коде — на украинском.

## Команды

Запускать из корня репозитория в Windows (локально есть `venv/`):

```bash
venv\Scripts\activate
pip install -r requirements.txt     # внимание: файл в кодировке UTF-16 LE
python manage.py runserver
python manage.py check
python manage.py test library       # tests.py сейчас пустой
python manage.py test library.tests.SomeTestCase.test_method
```

Линтер и форматтер не настроены.

## База данных

- MySQL (`game_library_db` на localhost:3306, utf8mb4), параметры заданы прямо в [config/settings.py](config/settings.py). `db.sqlite3` не используется (и игнорируется git).
- Структура таблиц задаётся SQL-дампом [database/gamevault_dump.sql](database/gamevault_dump.sql), **а не** миграциями Django. Все модели в [library/models.py](library/models.py) имеют `managed = False` и явный `db_table`, а в `library/migrations/` миграций нет. Сначала загрузите дамп в MySQL, затем `python manage.py migrate` — только для создания встроенных таблиц Django (sessions, contenttypes, admin, auth).
- Изменения схемы делаются в MySQL (с повторным экспортом дампа) и вручную переносятся в модель; `makemigrations` эти таблицы не изменит. В текущем дампе нет таблиц `external_accounts` и `external_library_items`, которые использует интеграция со Steam.
- Местами используется сырой SQL (например, `add_game_genres` в views.py вставляет строки в `game_genres` через `connection.cursor()`), так как `GameGenre` отображает связующую таблицу с составным первичным ключом.

## Архитектура

Один Django-проект `config/` с одним приложением `library/`. Все представления — функции, находятся в [library/views.py](library/views.py) (~1750 строк); маршруты в пространстве имён `library:` в [library/urls.py](library/urls.py).

**Аутентификация собственная, не `django.contrib.auth`.** `library.models.User` — неуправляемая модель над таблицей `users` с полем `password_hash`. При входе в сессию записывается `request.session['library_user_id']`; представления получают пользователя через `get_current_user(request)` и перенаправляют на `library:login`, если он `None`. Контекстный процессор [library/context_processors.py](library/context_processors.py) передаёт `current_library_user` во все шаблоны. Пароли хешируются через `make_password`/`check_password` из Django; `login_view` при успешном входе также переводит старые пароли в открытом виде на хеш. Не используйте `request.user`, `@login_required` или `django.contrib.auth.models.User` для пользователей приложения.

**Авторизация** основана на ролях из таблицы `roles`: `is_admin_user(user)` проверяет `user.role.name == 'admin'`; новые пользователи при регистрации получают роль `user`. Админские представления (модерация, управление играми/жанрами/рецензиями в `manage/...`) проверяют это вручную. Django-админка на `/admin/` — отдельная и работает через собственную аутентификацию Django.

**Ключевые моменты модели данных:**
- `Game` ↔ `Genre` — связь многие-ко-многим через `GameGenre` (`game_genres`). Хелперы `attach_visible_genres_to_*` в views.py прикрепляют к играм/записям ограниченный список жанров для шаблонов.
- `LibraryEntry` (пользователь + игра + статус), `Review` (оценка, используется для среднего рейтинга через `Avg('reviews__score')`), `SocialConnection` (отправитель/получатель со статусом `pending`/`accepted`; дружба проверяется симметрично через `are_friends`), `GameRequest` (заявки пользователей на добавление игр, одобряются/отклоняются в модерации), `Recommendation`.
- `User.is_private` управляет видимостью профиля и библиотеки для тех, кто не в друзьях.
- Рекомендации (представление `recommendations`) вычисляются в Python по жанрам игр из библиотеки пользователя и игр, которые он оценил на ≥ 8.

**Интеграция со Steam** находится в [library/services/steam_service.py](library/services/steam_service.py): вход через Steam OpenID (`steam/connect/` → `steam/callback/`), получение профиля и списка игр через Steam Web API и `sync_steam_library`, которая переносит игры в `ExternalLibraryItem`/`LibraryEntry`. Требуется переменная окружения `STEAM_API_KEY` и пакет `requests` (пока не указан в requirements.txt).

**Шаблоны и статика:** шаблоны в `library/templates/library/` наследуют `base.html`; единственный файл стилей — `library/static/library/css/style.css`. Загружаемые пользователями файлы (аватары, постеры игр) сохраняются в `media/` и раздаются Django только при `DEBUG = True`.
