from datetime import timedelta

from django.utils import timezone

from characteristics.models import (
    BalanceMatrix,
    CalculatedCharacteristic,
    SupportedCharacteristic,
)
from math_model.models import QualityAnalysis
from subcharacteristics.models import (
    CalculatedSubCharacteristic,
    SupportedSubCharacteristic,
)
from utils.tests import APITestCaseExpanded


class SupportedCharacteristicModelCoverageTestCase(APITestCaseExpanded):
    def setUp(self):
        self.org = self.get_organization()
        self.product = self.get_product(self.org)
        self.repository = self.get_repository(self.product)
        self.pre_config = self.product.release_configuration.first()
        self.analysis = QualityAnalysis.objects.create(repository=self.repository)

    def test_supported_characteristic_str_returns_name(self):
        characteristic = SupportedCharacteristic.objects.get(key="reliability")
        self.assertEqual(str(characteristic), "Reliability")

    def test_save_populates_key_from_name_and_name_from_key(self):
        char_without_key = SupportedCharacteristic.objects.create(
            name="Custom Security",
            key="",
        )
        self.assertEqual(char_without_key.key, "custom_security")

        char_without_name = SupportedCharacteristic.objects.create(
            name="",
            key="portability_level",
        )
        self.assertEqual(char_without_name.name, "Portability Level")

    def test_subcharacteristic_save_populates_key_from_name(self):
        sub = SupportedSubCharacteristic.objects.create(
            name="Custom Modifiability",
            key="",
        )
        self.assertEqual(sub.key, "custom_modifiability")

    def test_get_latest_characteristic_value_returns_none_or_latest_value(self):
        reliability = SupportedCharacteristic.objects.get(key="reliability")
        self.assertIsNone(reliability.get_latest_characteristic_value())

        now = timezone.now()
        other_repo = self.get_repository(self.product, name="Second Repository")
        other_analysis = QualityAnalysis.objects.create(repository=other_repo)
        CalculatedCharacteristic.objects.create(
            characteristic=reliability,
            repository=self.repository,
            analysis=self.analysis,
            value=0.61,
            created_at=now - timedelta(hours=1),
        )
        CalculatedCharacteristic.objects.create(
            characteristic=reliability,
            repository=other_repo,
            analysis=other_analysis,
            value=0.89,
            created_at=now,
        )

        self.assertEqual(reliability.get_latest_characteristic_value(), 0.89)

    def test_get_latest_characteristics_params_returns_weighted_characteristics(self):
        reliability = SupportedCharacteristic.objects.get(key="reliability")
        CalculatedCharacteristic.objects.create(
            characteristic=reliability,
            repository=self.repository,
            analysis=self.analysis,
            value=0.77,
        )
        SupportedCharacteristic.objects.create(
            key="unconfigured_characteristic",
            name="Unconfigured Characteristic",
        )

        params = reliability.get_latest_characteristics_params(self.pre_config)
        params_by_key = {item["key"]: item for item in params}

        self.assertIn("reliability", params_by_key)
        self.assertNotIn("unconfigured_characteristic", params_by_key)
        self.assertEqual(params_by_key["reliability"]["value"], 0.77)
        self.assertEqual(
            params_by_key["reliability"]["weight"],
            self.pre_config.get_characteristic_weight("reliability"),
        )

    def test_get_latest_subcharacteristics_params_returns_weighted_subcharacteristics(self):
        reliability = SupportedCharacteristic.objects.get(key="reliability")
        testing_status = SupportedSubCharacteristic.objects.get(key="testing_status")
        CalculatedSubCharacteristic.objects.create(
            subcharacteristic=testing_status,
            repository=self.repository,
            analysis=self.analysis,
            value=0.91,
        )
        extra_sub = SupportedSubCharacteristic.objects.create(
            key="extra_subcharacteristic",
            name="Extra Subcharacteristic",
        )
        reliability.subcharacteristics.add(extra_sub)

        sub_params = reliability.get_latest_subcharacteristics_params(self.pre_config)
        sub_params_by_key = {item["key"]: item for item in sub_params}

        self.assertIn("testing_status", sub_params_by_key)
        self.assertNotIn("extra_subcharacteristic", sub_params_by_key)
        self.assertEqual(sub_params_by_key["testing_status"]["value"], 0.91)
        self.assertEqual(
            sub_params_by_key["testing_status"]["weight"],
            self.pre_config.get_subcharacteristic_weight("testing_status"),
        )

    def test_has_unsupported_subcharacteristics_and_characteristics(self):
        reliability = SupportedCharacteristic.objects.get(key="reliability")
        self.assertEqual(
            reliability.has_unsupported_subcharacteristics(
                ["testing_status", "modifiability"]
            ),
            {"modifiability"},
        )
        self.assertEqual(
            SupportedCharacteristic.has_unsupported_characteristics(
                ["reliability", "unknown_characteristic"]
            ),
            {"unknown_characteristic"},
        )

    def test_balance_matrix_str_returns_formatted_relation(self):
        reliability = SupportedCharacteristic.objects.get(key="reliability")
        maintainability = SupportedCharacteristic.objects.get(key="maintainability")
        matrix = BalanceMatrix.objects.create(
            source_characteristic=reliability,
            target_characteristic=maintainability,
            relation_type="+",
        )
        self.assertEqual(str(matrix), "Reliability + Maintainability")
