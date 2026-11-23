"""Поштовий бекенд для розробки: лист у консолі runserver звичайним текстом.

Стандартний console-бекенд Django друкує MIME-повідомлення, а кирилиця в ньому закодована
base64 — посилання з листа не скопіюєш. Тут друкуємо тему, адресата й тіло як є.
"""

from django.core.mail.backends.console import EmailBackend


class ReadableConsoleBackend(EmailBackend):
    def write_message(self, message):
        self.stream.write(
            "\n" + "=" * 79 + "\n"
            f"ЛИСТ (не надіслано — EMAIL_HOST у .env порожній)\n"
            f"Кому: {', '.join(message.to)}\n"
            f"Тема: {message.subject}\n\n"
            f"{message.body}\n" + "=" * 79 + "\n"
        )
