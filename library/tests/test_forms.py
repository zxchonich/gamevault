from django.urls import reverse

from library.models import Game, GameGenre, Genre, User

from .base import GameVaultTestCase


class FormValidationTests(GameVaultTestCase):
    def setUp(self):
        self.admin = self.make_user("root", admin=True)

    def test_register_rejects_invalid_email(self):
        response = self.client.post(reverse("library:register"), {
            "username": "newbie", "email": "not-an-email", "password": "p", "password_confirm": "p",
        })

        self.assertEqual(response.context["error"], "Вкажіть коректну електронну адресу.")
        self.assertFalse(User.objects.filter(username="newbie").exists())

    def test_register_required_fields_message(self):
        response = self.client.post(reverse("library:register"), {"username": "", "email": "", "password": ""})

        self.assertEqual(response.context["error"], "Заповніть усі обов’язкові поля.")

    def test_edit_profile_errors(self):
        alice = self.make_user("alice")
        self.make_user("bob")
        self.login(alice)
        url = reverse("library:edit_profile")

        cases = [
            ({"username": "", "email": "a@example.com"}, "Логін та email не можуть бути порожніми."),
            ({"username": "bob", "email": "a@example.com"}, "Користувач із таким логіном уже існує."),
            ({"username": "alice", "email": "bob@example.com"}, "Користувач із таким email уже існує."),
            ({"username": "alice", "email": "alice@example.com", "password": "x", "password_confirm": "y"},
             "Паролі не збігаються."),
        ]
        for data, error in cases:
            with self.subTest(error=error):
                self.assertEqual(self.client.post(url, data).context["error"], error)

    def test_game_form_rejects_invalid_date_instead_of_crashing(self):
        self.login(self.admin)

        response = self.client.post(reverse("library:admin_game_add"), {"title": "Celeste", "release_date": "abc"})

        self.assertEqual(response.status_code, 200)
        self.assertIn("Некоректна дата виходу.", self.messages_of(response))
        self.assertFalse(Game.objects.filter(title="Celeste").exists())

    def test_game_form_keeps_valid_genres_and_ignores_unknown(self):
        action = Genre.objects.create(name="Action")
        self.login(self.admin)

        self.client.post(reverse("library:admin_game_add"),
                         {"title": "Celeste", "release_date": "2018-01-25", "genres": [action.id, 99999, "x"]})

        game = Game.objects.get(title="Celeste")
        self.assertEqual(str(game.release_date), "2018-01-25")
        self.assertEqual(list(GameGenre.objects.filter(game=game).values_list("genre_id", flat=True)), [action.id])

    def test_genre_validation(self):
        Genre.objects.create(name="Action")
        self.login(self.admin)
        url = reverse("library:admin_genre_list")

        cases = [("", "Назва жанру не може бути порожньою."), ("action", "Такий жанр уже існує."),
                 ("x" * 51, "Значення задовге (максимум 50 символів).")]
        for name, error in cases:
            with self.subTest(name=name[:10]):
                response = self.client.post(url, {"name": name}, follow=True)
                self.assertIn(error, self.messages_of(response))
        self.assertEqual(Genre.objects.count(), 1)

    def test_request_game_requires_title(self):
        self.login(self.make_user("alice"))

        response = self.client.post(reverse("library:request_game"), {"title": "  "}, follow=True)

        self.assertIn("Вкажіть назву гри.", self.messages_of(response))

    def test_profile_shows_status_labels(self):
        alice = self.make_user("alice")
        self.make_entry(alice, self.make_game("Hades"), status="completed")
        self.login(alice)

        self.assertContains(self.client.get(reverse("library:profile")), "<span>Пройдено</span>")
