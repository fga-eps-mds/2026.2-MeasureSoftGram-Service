"""
Cálculo da característica Segurança (US14.01) a partir do payload da Action:
métricas SAST por arquivo (FIL) e alertas de segurança do GitHub (TRK).
"""

import copy
from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from freezegun import freeze_time
from rest_framework import status
from rest_framework.authtoken.models import Token

from characteristics.models import CalculatedCharacteristic
from math_model import utils
from math_model.services import MathModelServices
from measures.models import CalculatedMeasure
from release_configuration.models import ReleaseConfiguration
from release_configuration.serializers import ReleaseConfigurationSerializer
from subcharacteristics.models import CalculatedSubCharacteristic
from tsqmi.models import TSQMI
from utils import staticfiles
from utils.tests import APITestCaseExpanded

SECURITY_MEASURES = {
    "security_rating_measure",
    "absence_of_vulnerabilities",
    "security_review_rating_measure",
    "security_alerts_resolution",
}


def _security_payload(with_alerts=True):
    payload = {
        "github": {
            "metrics": [
                {"name": "security_alerts_open", "value": 1},
                {"name": "security_alerts_closed", "value": 9},
            ],
        },
        "sonarqube": {
            "components": [
                {
                    "qualifier": "FIL",
                    "path": "src/foo.py",
                    "measures": [
                        {"metric": "security_rating", "value": 1.0},
                        {"metric": "security_review_rating", "value": 1.0},
                        {"metric": "vulnerabilities", "value": 0},
                        {"metric": "ncloc", "value": 100},
                    ],
                },
                {
                    "qualifier": "FIL",
                    "path": "src/bar.py",
                    "measures": [
                        {"metric": "security_rating", "value": 3.0},
                        {"metric": "security_review_rating", "value": 5.0},
                        {"metric": "vulnerabilities", "value": 1},
                        {"metric": "ncloc", "value": 2000},
                    ],
                },
            ],
        },
    }
    if not with_alerts:
        payload["github"]["metrics"] = []
    return payload


def _security_release_config():
    data = copy.deepcopy(staticfiles.SECURITY_PRE_CONFIG)
    data["characteristics"][0]["weight"] = 100
    return data


@freeze_time("2024-09-08 20:00:00")
class SecurityCharacteristicCalculationTest(APITestCaseExpanded):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="test-user", password="test-pass")
        self.client.force_authenticate(self.user, token=Token.objects.create(user=self.user))

        self.org = self.get_organization()
        self.product = self.get_product(self.org)
        self.repository = self.get_repository(self.product)
        # Mais recente que a pré-configuração padrão criada junto com o produto.
        ReleaseConfiguration.objects.create(
            name="Security pre-config",
            data=_security_release_config(),
            product=self.product,
            created_at=timezone.now() + timedelta(minutes=1),
        )

        self.url = (
            f"/api/v1/organizations/{self.org.id}"
            f"/products/{self.product.id}"
            f"/repositories/{self.repository.id}"
            f"/calculate/math-model/"
        )

    def test_security_is_calculated_from_metrics_to_tsqmi(self):
        response = self.client.post(self.url, _security_payload(), format="json")

        assert response.status_code == status.HTTP_201_CREATED, response.content

        measures = {m.measure.key: m.value for m in CalculatedMeasure.objects.all()}
        assert set(measures) == SECURITY_MEASURES
        assert all(0 <= value <= 1 for value in measures.values())
        # 9 de 10 alertas fechados: (90 - 45) / (100 - 45)
        assert measures["security_alerts_resolution"] == pytest.approx(45 / 55)

        subcharacteristics = set(
            CalculatedSubCharacteristic.objects.values_list("subcharacteristic__key", flat=True)
        )
        assert subcharacteristics == {"confidentiality", "integrity"}
        assert CalculatedCharacteristic.objects.get().characteristic.key == "security"
        assert TSQMI.objects.count() == 1

    def test_missing_alerts_skip_only_the_dependent_measure(self):
        response = self.client.post(self.url, _security_payload(with_alerts=False), format="json")

        assert response.status_code == status.HTTP_201_CREATED, response.content

        measures = set(CalculatedMeasure.objects.values_list("measure__key", flat=True))
        assert measures == SECURITY_MEASURES - {"security_alerts_resolution"}
        assert CalculatedCharacteristic.objects.get().characteristic.key == "security"

    def test_release_config_without_security_ignores_security_metrics(self):
        release_config = ReleaseConfiguration.objects.create(
            name="Default pre-config",
            data=staticfiles.DEFAULT_PRE_CONFIG,
            product=self.product,
        )
        services = MathModelServices(self.repository, self.product)
        collected = services.build_collected_metrics(_security_payload())
        _, _, measure_keys = utils.parse_release_configuration(
            ReleaseConfigurationSerializer(release_config).data,
        )

        _, values = services.build_calculated_measures(measure_keys, release_config, collected)

        assert SECURITY_MEASURES.isdisjoint(values)
