"""Dados de demonstração sob pedido (GET .../repositories/<id>/demo-data/).

Garante as regras combinadas com o PO depois da #150 (BUG05.06):
- a resposta é marcada como demonstração (is_demo + aviso);
- nada é gravado no banco, nem a pré-configuração padrão;
- repositório com coleta real não recebe demonstração (409);
- o endpoint some quando DEMO_DATA_ENABLED=False;
- o usuário só vê repositórios das próprias organizações.
"""

from datetime import datetime

from django.contrib.auth import get_user_model
from django.test import override_settings
from freezegun import freeze_time
from rest_framework import status
from rest_framework.authtoken.models import Token

from characteristics.models import CalculatedCharacteristic
from math_model.demo import DEMO_COLLECTIONS, build_demo_data
from measures.models import CalculatedMeasure
from metrics.models import CollectedMetric, SupportedMetric
from release_configuration.models import ReleaseConfiguration
from subcharacteristics.models import CalculatedSubCharacteristic
from tsqmi.models import TSQMI
from utils.tests import APITestCaseExpanded

PERSISTED_MODELS = (
    CollectedMetric,
    CalculatedMeasure,
    CalculatedSubCharacteristic,
    CalculatedCharacteristic,
    TSQMI,
    ReleaseConfiguration,
)


@freeze_time("2026-11-06 12:00:00")
class DemoDataEndpointTest(APITestCaseExpanded):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="demo-user", password="demo-pass")
        self.client.force_authenticate(self.user, token=Token.objects.create(user=self.user))
        self.org = self.get_organization()
        self.product = self.get_product(self.org)
        self.repository = self.get_repository(self.product)
        self.url = (
            f"/api/v1/organizations/{self.org.id}"
            f"/products/{self.product.id}"
            f"/repositories/{self.repository.id}"
            f"/demo-data/"
        )

    def _counts(self):
        return {model.__name__: model.objects.count() for model in PERSISTED_MODELS}

    def test_returns_data_marked_as_demo(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertIs(body["is_demo"], True)
        self.assertIn("demonstração", body["notice"])
        self.assertIsNotNone(body["latest_tsqmi"]["value"])
        self.assertGreaterEqual(body["latest_tsqmi"]["value"], 0)
        self.assertLessEqual(body["latest_tsqmi"]["value"], 1)
        self.assertEqual(len(body["tsqmi_history"]), DEMO_COLLECTIONS)

        results = body["historical_characteristics"]["results"]
        self.assertGreater(len(results), 0)
        for characteristic in results:
            self.assertEqual(len(characteristic["history"]), DEMO_COLLECTIONS)
            dates = [datetime.fromisoformat(point["created_at"]) for point in characteristic["history"]]
            self.assertEqual(dates, sorted(dates))

    def test_does_not_persist_anything(self):
        before = self._counts()

        response = self.client.get(self.url)
        self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(self._counts(), before)

    def test_does_not_save_default_configuration_when_product_has_none(self):
        self.product.release_configuration.all().delete()
        before = self._counts()

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(self._counts(), before)
        self.assertFalse(self.product.release_configuration.exists())

    def test_is_deterministic_per_repository(self):
        first = build_demo_data(self.repository)
        second = build_demo_data(self.repository)

        self.assertEqual(first, second)

    def test_refuses_repository_with_real_collected_metrics(self):
        CollectedMetric.objects.create(
            value=10,
            metric=SupportedMetric.objects.get(key="ncloc"),
            repository=self.repository,
            qualifier="FIL",
            path="src/real.py",
        )

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)

    def test_refuses_repository_with_real_tsqmi(self):
        TSQMI.objects.create(repository=self.repository, value=0.7)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)

    @override_settings(DEMO_DATA_ENABLED=False)
    def test_returns_404_when_disabled(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_returns_404_for_repository_of_another_organization(self):
        other_org = self.get_organization(name="Other Org", add_user=False)
        other_product = self.get_product(other_org, name="Other Product")
        other_repository = self.get_repository(other_product)
        url = (
            f"/api/v1/organizations/{other_org.id}"
            f"/products/{other_product.id}"
            f"/repositories/{other_repository.id}"
            f"/demo-data/"
        )

        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_requires_authentication(self):
        self.client.force_authenticate(user=None)

        response = self.client.get(self.url)

        self.assertIn(response.status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))
