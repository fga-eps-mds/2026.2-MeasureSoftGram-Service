from datetime import timedelta

from django.utils import timezone

from measures.models import CalculatedMeasure, SupportedMeasure
from metrics.models import CollectedMetric, SupportedMetric
from utils.tests import APITestCaseExpanded


class SupportedMeasureModelCoverageTestCase(APITestCaseExpanded):
    def setUp(self):
        self.org = self.get_organization()
        self.product = self.get_product(self.org)
        self.repository = self.get_repository(self.product)

    def test_supported_measure_str_returns_name(self):
        measure = SupportedMeasure.objects.get(key="test_coverage")
        self.assertEqual(str(measure), measure.name)

    def test_get_latest_metric_params_defaults_none_values_to_zero(self):
        measure = SupportedMeasure.objects.get(key="ci_feedback_time")
        params_when_empty = measure.get_latest_metric_params(self.repository)

        self.assertEqual(
            params_when_empty,
            {
                "sum_ci_feedback_times": 0,
                "total_builds": 0,
            },
        )

        sum_metric = SupportedMetric.objects.get(key="sum_ci_feedback_times")
        builds_metric = SupportedMetric.objects.get(key="total_builds")
        CollectedMetric.objects.create(
            metric=sum_metric,
            repository=self.repository,
            qualifier="FIL",
            value=180.0,
        )
        CollectedMetric.objects.create(
            metric=builds_metric,
            repository=self.repository,
            qualifier="FIL",
            value=6.0,
        )

        params_when_collected = measure.get_latest_metric_params(self.repository)
        self.assertEqual(
            params_when_collected,
            {
                "sum_ci_feedback_times": 180.0,
                "total_builds": 6.0,
            },
        )

    def test_has_unsupported_measures_returns_only_unsupported_keys(self):
        unsupported = SupportedMeasure.has_unsupported_measures(
            ["test_coverage", "nonexistent_measure"]
        )
        self.assertEqual(unsupported, {"nonexistent_measure"})
        self.assertEqual(
            SupportedMeasure.has_unsupported_measures(["test_coverage"]),
            set(),
        )

    def test_get_latest_measure_value_returns_none_or_most_recent_value(self):
        measure = SupportedMeasure.objects.get(key="test_coverage")
        self.assertIsNone(measure.get_latest_measure_value())

        now = timezone.now()
        CalculatedMeasure.objects.create(
            measure=measure,
            repository=self.repository,
            value=0.45,
            created_at=now - timedelta(hours=2),
        )
        CalculatedMeasure.objects.create(
            measure=measure,
            repository=self.repository,
            value=0.82,
            created_at=now,
        )

        self.assertEqual(measure.get_latest_measure_value(), 0.82)
