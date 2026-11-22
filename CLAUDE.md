# CLAUDE.md

Этот файл содержит инструкции для Claude Code (claude.ai/code) по работе с кодом в этом репозитории.

## Проект

GameVault — курсовой проект на Django: веб-приложение для агрегации персональных игровых библиотек. Каталог игр с поиском и фильтрацией, личная библиотека со статусами прохождения, рецензии и оценки, профили пользователей, друзья и заявки в друзья, персональные рекомендации, заявки на добавление игр с модерацией, админ-управление играми и жанрами, синхронизация библиотеки Steam. Тексты интерфейса и комментарии в коде — на украинском.

## Команды

Запускать из корня репозитория в Windows (локально есть `venv/`):

```bash
venv\Scripts\activate
pip install -r requirements.txt     # обновлять через pip freeze > requirements.txt (сохранять в UTF-8)
python manage.py runserver
python manage.py check
python manage.py test library --keepdb                       # все тесты (~1-2 с с --keepdb)
python manage.py test library.tests.test_steam --keepdb      # один модуль
python manage.py test library.tests.test_auth.LoginLogoutTests.test_login_success_rotates_session --keepdb
```

Линтер и форматтер не настроены.

Тесты (`library/tests/`) работают на MySQL, поэтому служба должна быть запущена. Таблицы приложения `managed = False`, поэтому [library/test_runner.py](library/test_runner.py) после создания тестовой БД загружает в неё [database/schema.sql](database/schema.sql) — при изменении схемы обновите schema.sql, иначе тесты разойдутся с реальной БД (с `--keepdb` после этого один раз запустите без него). Фабрики данных и `login()` — в `library/tests/base.py`. Внешние вызовы Steam в тестах мокаются по месту использования (`library.views.fetch_store_details`, `library.steam_views.sync_steam_library`, `library.services.steam_service.requests`).

## База данных

- MySQL (`game_library_db` на localhost:3306, utf8mb4). Параметры БД, `SECRET_KEY`, `DEBUG`, `ALLOWED_HOSTS` и `STEAM_API_KEY` читаются из `.env` (не в git; шаблон — [.env.example](.env.example)) через `python-dotenv` в [config/settings.py](config/settings.py). `db.sqlite3` не используется. Служба MySQL на этой машине (`MySQL96`) запускается вручную и требует прав администратора: `net start MySQL96`.
- Изменения схемы оформляются SQL-файлами в [database/migrations/](database/migrations/) (`001_steam.sql`, `002_...`), применяются к локальной БД, после чего [database/schema.sql](database/schema.sql) переэкспортируется: `mysqldump --no-data --skip-comments --set-gtid-purged=OFF --skip-add-drop-table` по таблицам приложения, затем убрать `AUTO_INCREMENT=N` и сохранить `INSERT` ролей. Репозиторий публичный: данные пользователей в git не коммитить. Старый [database/gamevault_dump.sql](database/gamevault_dump.sql) (с данными) устарел и для разворачивания не подходит.
- Структура таблиц задаётся [database/schema.sql](database/schema.sql), **а не** миграциями Django. Все модели в [library/models.py](library/models.py) имеют `managed = False` и явный `db_table`, а в `library/migrations/` миграций нет. Сначала загрузите схему в MySQL, затем `python manage.py migrate` — только для создания встроенных таблиц Django (sessions, contenttypes, admin, auth).
- Изменения схемы вручную переносятся в модель; `makemigrations` эти таблицы не изменит.
- Местами используется сырой SQL (например, `add_game_genres` в views.py вставляет строки в `game_genres` через `connection.cursor()`), так как `GameGenre` отображает связующую таблицу с составным первичным ключом.

## Архитектура

Один Django-проект `config/` с одним приложением `library/`. Все представления — функции: основные в [library/views.py](library/views.py) (~1800 строк), всё связанное со Steam — в [library/steam_views.py](library/steam_views.py) (импортирует хелперы `get_current_user`, `is_admin_user`, `can_view_profile` из views.py, поэтому views.py не должен импортировать steam_views). Маршруты в пространстве имён `library:` в [library/urls.py](library/urls.py). Видимость чужого профиля/библиотеки проверяет `can_view_profile(viewer, owner)` (приватный профиль виден только друзьям).

**Аутентификация собственная, не `django.contrib.auth`.** `library.models.User` — неуправляемая модель над таблицей `users` с полем `password_hash`. При входе в сессию записывается `request.session['library_user_id']`; представления получают пользователя через `get_current_user(request)` и перенаправляют на `library:login`, если он `None`. Контекстный процессор [library/context_processors.py](library/context_processors.py) передаёт `current_library_user` во все шаблоны. Пароли хешируются через `make_password`/`check_password` из Django; оставшиеся пароли в открытом виде хешируются командой `python manage.py hash_plain_passwords [--dry-run]`. Не используйте `request.user`, `@login_required` или `django.contrib.auth.models.User` для пользователей приложения.

**Авторизация** основана на ролях из таблицы `roles`: `is_admin_user(user)` проверяет `user.role.name == 'admin'`; новые пользователи при регистрации получают роль `user`. Админские представления (модерация, управление играми/жанрами/рецензиями в `manage/...`) проверяют это вручную. Django-админка на `/admin/` — отдельная и работает через собственную аутентификацию Django.

**Действия, меняющие данные, — только POST.** Такие view помечены `@require_POST`, а в шаблонах вызываются формой `<form class="inline-post-form" method="post">` с `{% csrf_token %}` и `<button class="link-button ...">`, а не ссылкой. `.inline-post-form` (`display: contents`) и `:where(.link-button)` в конце style.css делают кнопку визуально идентичной ссылке; если кнопка стоит в контейнере, где ссылки стилизуются через `.X a`, добавьте в это правило `.X .link-button`.

**Ключевые моменты модели данных:**
- `Game` ↔ `Genre` — связь многие-ко-многим через `GameGenre` (`game_genres`). Хелперы `attach_visible_genres_to_*` в views.py прикрепляют к играм/записям ограниченный список жанров для шаблонов.
- `LibraryEntry` (пользователь + игра + статус), `Review` (оценка, используется для среднего рейтинга через `Avg('reviews__score')`), `SocialConnection` (отправитель/получатель со статусом `pending`/`accepted`; дружба проверяется симметрично через `are_friends`), `GameRequest` (заявки пользователей на добавление игр, одобряются/отклоняются в модерации), `Recommendation`.
- `User.is_private` управляет видимостью профиля и библиотеки для тех, кто не в друзьях.
- Рекомендации (представление `recommendations`) вычисляются в Python по жанрам игр из библиотеки пользователя и игр, которые он оценил на ≥ 8.

**Интеграция со Steam** находится в [library/services/steam_service.py](library/services/steam_service.py): вход через Steam OpenID (`steam/connect/` → `steam/callback/`), получение профиля и списка игр через Steam Web API и `sync_steam_library`, которая переносит игры в `ExternalLibraryItem` (удаляя пропавшие из Steam) и добавляет совпавшие по `Game.steam_appid` игры в `LibraryEntry` (только новые записи; статусы существующих не меняются). Ошибки Steam (нет ключа, сеть, закрытый профиль) выбрасываются как `SteamError` с текстом для пользователя. Требуется `STEAM_API_KEY` в `.env`.

Каталог связан со Steam через `Game.steam_appid`: игра с appid автоматически добавляется в библиотеки владельцев (`link_game_to_steam_owners`) при назначении appid (админская форма, страница `manage/steam-matching/`, одобрение заявки) и при синхронизации. Пользователь видит импорт на `steam/library/` (чужой — `users/<id>/steam/`) и может предложить игру в каталог — это `GameRequest` со `steam_appid`. При одобрении такой заявки и при `?steam_appid=` на админской форме данные и постер подтягиваются из публичного Steam Store API (`fetch_store_details`, `download_steam_poster`). Обложки в списках — CDN Steam по appid (`ExternalLibraryItem.cover_url`); у части новых игр их нет, поэтому `<img onerror="this.remove()">`.

**Шаблоны и статика:** шаблоны в `library/templates/library/` наследуют `base.html`; единственный файл стилей — `library/static/library/css/style.css`. Загружаемые пользователями файлы (аватары, постеры игр) сохраняются в `media/` и раздаются Django только при `DEBUG = True`.
