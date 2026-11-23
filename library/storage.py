"""Прибирання завантажених файлів (аватари, постери), які більше ніде не використовуються."""

from django.core.files.storage import default_storage


def delete_unused_file(model, field, name):
    """Видаляє файл name зі сховища, якщо жоден запис model.field на нього більше не посилається.

    Перевірка потрібна, бо кілька записів можуть мати той самий файл (наприклад, постер
    зі Steam з однаковою назвою). Помилки файлової системи не заважають основній дії."""
    if not name or model.objects.filter(**{field: name}).exists():
        return False
    try:
        if default_storage.exists(name):
            default_storage.delete(name)
            return True
    except OSError:
        pass
    return False
