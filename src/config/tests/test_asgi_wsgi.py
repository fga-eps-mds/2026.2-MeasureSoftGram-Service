import importlib
import os
from unittest import mock

from django.core.handlers.asgi import ASGIHandler
from django.core.handlers.wsgi import WSGIHandler
from django.test import SimpleTestCase


class AsgiWsgiConfigTestCase(SimpleTestCase):
    def test_asgi_application_is_callable(self):
        with mock.patch.dict(os.environ):
            self.assertEqual(os.environ.get("DJANGO_SETTINGS_MODULE"), "config.settings.test")

            asgi_module = importlib.import_module("config.asgi")
            asgi_module = importlib.reload(asgi_module)

            self.assertEqual(os.environ.get("DJANGO_SETTINGS_MODULE"), "config.settings.test")
            self.assertTrue(callable(asgi_module.application))
            self.assertIsInstance(asgi_module.application, ASGIHandler)

    def test_wsgi_application_is_callable(self):
        with mock.patch.dict(os.environ):
            self.assertEqual(os.environ.get("DJANGO_SETTINGS_MODULE"), "config.settings.test")

            wsgi_module = importlib.import_module("config.wsgi")
            wsgi_module = importlib.reload(wsgi_module)

            self.assertEqual(os.environ.get("DJANGO_SETTINGS_MODULE"), "config.settings.test")
            self.assertTrue(callable(wsgi_module.application))
            self.assertIsInstance(wsgi_module.application, WSGIHandler)

    def test_asgi_sets_default_production_settings_when_unset(self):
        with mock.patch.dict(os.environ):
            os.environ.pop("DJANGO_SETTINGS_MODULE", None)

            asgi_module = importlib.import_module("config.asgi")
            asgi_module = importlib.reload(asgi_module)

            self.assertEqual(os.environ.get("DJANGO_SETTINGS_MODULE"), "config.settings.production")
            self.assertTrue(callable(asgi_module.application))
            self.assertIsInstance(asgi_module.application, ASGIHandler)

    def test_wsgi_sets_default_production_settings_when_unset(self):
        with mock.patch.dict(os.environ):
            os.environ.pop("DJANGO_SETTINGS_MODULE", None)

            wsgi_module = importlib.import_module("config.wsgi")
            wsgi_module = importlib.reload(wsgi_module)

            self.assertEqual(os.environ.get("DJANGO_SETTINGS_MODULE"), "config.settings.production")
            self.assertTrue(callable(wsgi_module.application))
            self.assertIsInstance(wsgi_module.application, WSGIHandler)
