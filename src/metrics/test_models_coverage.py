from datetime import timedelta

from django.utils import timezone

from math_model.models import QualityAnalysis
from metrics.models import CollectedMetric, SupportedMetric
from utils.tests import APITestCaseExpanded


class SupportedMetricModelCoverageTestCase(APITestCaseExpanded):
    def setUp(self):
        self.org = self.get_organization()
        self.product = self.get_product(self.org)
        self.repository = self.get_repository(self.product)
        self.analysis = QualityAnalysis.objects.create(repository=self.repository)

    def test_supported_metric_str_returns_key(self):
        metric = SupportedMetric.objects.get(key="coverage")
        self.assertEqual(str(metric), "coverage")

    def test_get_latest_metric_values_returns_empty_list_when_none_collected(self):
        metric = SupportedMetric.objects.get(key="coverage")
        self.assertEqual(
            metric.get_latest_metric_values(self.repository, qualifier="FIL"),
            [],
        )

    def test_get_latest_metric_value_for_listed_metric_excludes_empty_and_old_files(self):
        coverage_metric = SupportedMetric.objects.get(key="coverage")
        ncloc_metric = SupportedMetric.objects.get(key="ncloc")
        now = timezone.now()

        CollectedMetric.objects.create(
            metric=coverage_metric,
            repository=self.repository,
            analysis=self.analysis,
            path="src/module.py",
            qualifier="FIL",
            value=85.0,
            created_at=now,
        )
        CollectedMetric.objects.create(
            metric=ncloc_metric,
            repository=self.repository,
            analysis=self.analysis,
            path="src/module.py",
            qualifier="FIL",
            value=100.0,
            created_at=now,
        )

        CollectedMetric.objects.create(
            metric=coverage_metric,
            repository=self.repository,
            analysis=self.analysis,
            path="src/__init__.py",
            qualifier="FIL",
            value=0.0,
            created_at=now,
        )
        CollectedMetric.objects.create(
            metric=ncloc_metric,
            repository=self.repository,
            analysis=self.analysis,
            path="src/__init__.py",
            qualifier="FIL",
            value=0.0,
            created_at=now,
        )

        CollectedMetric.objects.create(
            metric=coverage_metric,
            repository=self.repository,
            analysis=self.analysis,
            path="src/legacy.py",
            qualifier="FIL",
            value=40.0,
            created_at=now - timedelta(minutes=30),
        )

        self.assertEqual(
            coverage_metric.get_latest_metric_value(self.repository),
            [85.0],
        )

    def test_get_latest_metric_value_for_uts_metric_returns_uts_values(self):
        tests_metric = SupportedMetric.objects.get(key="tests")
        ncloc_metric = SupportedMetric.objects.get(key="ncloc")
        now = timezone.now()

        CollectedMetric.objects.create(
            metric=tests_metric,
            repository=self.repository,
            analysis=self.analysis,
            path="tests/test_sample.py",
            qualifier="UTS",
            value=14.0,
            created_at=now,
        )
        CollectedMetric.objects.create(
            metric=ncloc_metric,
            repository=self.repository,
            analysis=self.analysis,
            path="tests/test_sample.py",
            qualifier="UTS",
            value=60.0,
            created_at=now,
        )

        self.assertEqual(
            tests_metric.get_latest_metric_value(self.repository),
            [14.0],
        )

    def test_get_latest_metric_value_for_github_metric_returns_latest_or_none(self):
        issues_metric = SupportedMetric.objects.get(key="total_issues")
        self.assertIsNone(issues_metric.get_latest_metric_value(self.repository))

        now = timezone.now()
        CollectedMetric.objects.create(
            metric=issues_metric,
            repository=self.repository,
            analysis=self.analysis,
            qualifier="FIL",
            value=8.0,
            created_at=now - timedelta(hours=1),
        )
        CollectedMetric.objects.create(
            metric=issues_metric,
            repository=self.repository,
            analysis=self.analysis,
            qualifier="FIL",
            value=12.0,
            created_at=now,
        )

        self.assertEqual(
            issues_metric.get_latest_metric_value(self.repository),
            12.0,
        )

    def test_get_latest_metric_value_for_trk_metric_returns_latest_or_none(self):
        ncloc_metric = SupportedMetric.objects.get(key="ncloc")
        self.assertIsNone(ncloc_metric.get_latest_metric_value(self.repository))

        now = timezone.now()
        CollectedMetric.objects.create(
            metric=ncloc_metric,
            repository=self.repository,
            analysis=self.analysis,
            qualifier="TRK",
            value=500.0,
            created_at=now - timedelta(hours=1),
        )
        CollectedMetric.objects.create(
            metric=ncloc_metric,
            repository=self.repository,
            analysis=self.analysis,
            qualifier="TRK",
            value=750.0,
            created_at=now,
        )

        self.assertEqual(
            ncloc_metric.get_latest_metric_value(self.repository),
            750.0,
        )
