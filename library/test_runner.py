"""Тестовий раннер: таблиці застосунку мають managed = False, тому Django їх не створює.
Після створення тестової БД завантажуємо в неї database/schema.sql — ту саму схему,
що й у робочій БД (складений ключ game_genres, ролі тощо)."""

import hashlib
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import connections
from django.test.runner import DiscoverRunner

SCHEMA_PATH = Path(settings.BASE_DIR) / "database" / "schema.sql"
SCHEMA_VERSION_TABLE = "test_schema_version"


def split_sql(sql):
    lines = [line for line in sql.splitlines() if not line.lstrip().startswith("--")]
    statements = "\n".join(lines).split(";\n")
    return [s.strip().rstrip(";") for s in statements if s.strip().rstrip(";").strip()]


def load_schema(connection):
    sql = SCHEMA_PATH.read_text(encoding="utf-8")
    schema_hash = hashlib.sha256(sql.encode("utf-8")).hexdigest()

    with connection.cursor() as cursor:
        if SCHEMA_VERSION_TABLE in connection.introspection.table_names(cursor):
            # --keepdb: схема вже завантажена; перевіряємо, що вона не застаріла.
            cursor.execute(f"SELECT hash FROM {SCHEMA_VERSION_TABLE}")
            row = cursor.fetchone()
            if row and row[0] == schema_hash:
                return
            raise ImproperlyConfigured(
                "database/schema.sql змінився після створення тестової БД. "
                "Запустіть тести один раз без --keepdb (з --noinput), щоб перестворити її."
            )

        for statement in split_sql(sql):
            cursor.execute(statement)

        cursor.execute(f"CREATE TABLE {SCHEMA_VERSION_TABLE} (hash char(64) NOT NULL)")
        cursor.execute(f"INSERT INTO {SCHEMA_VERSION_TABLE} (hash) VALUES (%s)", [schema_hash])


class SchemaTestRunner(DiscoverRunner):
    def setup_test_environment(self, **kwargs):
        super().setup_test_environment(**kwargs)
        # PBKDF2 навмисно повільний; у тестах це лише гальмує make_user.
        settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

    def setup_databases(self, **kwargs):
        old_config = super().setup_databases(**kwargs)

        for alias in connections:
            load_schema(connections[alias])

        return old_config
