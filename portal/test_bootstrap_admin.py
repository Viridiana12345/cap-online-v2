from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command, CommandError
from django.test import TestCase


class BootstrapAdminTests(TestCase):
    def run_command(self, **env):
        with patch.dict("os.environ", env, clear=True):
            call_command("bootstrap_admin", stdout=StringIO())

    def test_disabled_by_default(self):
        self.run_command()
        self.assertFalse(get_user_model().objects.exists())

    def test_creates_admin_and_does_not_reset_on_redeploy(self):
        env = dict(CAP_CREATE_ADMIN="true", CAP_ADMIN_USERNAME="admin-test",
                   CAP_ADMIN_EMAIL="admin@example.com", CAP_ADMIN_PASSWORD="River!Cactus-7428")
        self.run_command(**env)
        user = get_user_model().objects.get(username="admin-test")
        self.assertTrue(user.is_superuser and user.is_staff)
        self.assertTrue(user.check_password(env["CAP_ADMIN_PASSWORD"]))
        saved = user.password
        self.run_command(**{**env, "CAP_ADMIN_PASSWORD": "Changed!Password-943"})
        user.refresh_from_db()
        self.assertEqual(user.password, saved)

    def test_never_promotes_existing_user(self):
        user = get_user_model().objects.create_user("existing")
        self.run_command(CAP_CREATE_ADMIN="true", CAP_ADMIN_USERNAME="existing")
        user.refresh_from_db()
        self.assertFalse(user.is_superuser)

    def test_incomplete_or_weak_credentials_fail(self):
        for password in ("", "123"):
            with self.subTest(password=password), self.assertRaises(CommandError):
                self.run_command(CAP_CREATE_ADMIN="true", CAP_ADMIN_USERNAME="new-admin",
                                 CAP_ADMIN_EMAIL="admin@example.com", CAP_ADMIN_PASSWORD=password)
        self.assertFalse(get_user_model().objects.exists())
