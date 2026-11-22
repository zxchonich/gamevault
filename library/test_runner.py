"""Тестовий раннер: таблиці застосунку мають managed = False, тому Django їх не створює.
Після створення тестової БД завантажуємо в неї database/schema.sql — ту саму схему,
що й у робочій БД (складений ключ game_genres, ролі тощо)."""

from pathlib import Path

from django.conf import settings
from django.db import connections
from django.test.runner import DiscoverRunner

SCHEMA_PATH = Path(settings.BASE_DIR) / "database" / "schema.sql"


def split_sql(sql):
    lines = [line for line in sql.splitlines() if not line.lstrip().startswith("--")]
    statements = "\n".join(lines).split(";\n")
    return [s.strip().rstrip(";") for s in statements if s.strip().rstrip(";").strip()]


def load_schema(connection):
    with connection.cursor() as cursor:
        if "games" in connection.introspection.table_names(cursor):
            return  # --keepdb: схема вже завантажена

        for statement in split_sql(SCHEMA_PATH.read_text(encoding="utf-8")):
            cursor.execute(statement)


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
