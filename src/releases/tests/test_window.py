from datetime import timedelta

from django.utils import timezone

from goals.models import Goal
from metrics.models import CollectedMetric, SupportedMetric
from releases.models import Release
from releases.window import in_release_window, latest_in_release_window
from utils.tests import APITestCaseExpanded


class ReleaseWindowTestCase(APITestCaseExpanded):
    def setUp(self):
        self.user = self.get_or_create_test_user()
        self.org = self.get_organization()
        self.product = self.get_product(self.org)
        self.repository = self.get_repository(self.product)
        self.now = timezone.now()
        goal = Goal.objects.create(
            created_by=self.user,
            product=self.product,
            data={"reliability": 50, "maintainability": 50},
        )
        self.release = Release.objects.create(
            release_name="R1",
            start_at=self.now - timedelta(days=10),
            end_at=self.now,
            created_by=self.user,
            product=self.product,
            goal=goal,
        )
        self.metric = SupportedMetric.objects.get(key="coverage")

    def collect(self, created_at, value=1.0):
        return CollectedMetric.objects.create(
            metric=self.metric,
            value=value,
            path="src/a.py",
            qualifier="FIL",
            repository=self.repository,
            created_at=created_at,
        )

    def test_latest_ignores_values_outside_the_window(self):
        self.collect(self.now - timedelta(days=11), value=1.0)
        inside = self.collect(self.now - timedelta(days=1), value=2.0)
        self.collect(self.now + timedelta(days=1), value=3.0)

        latest = latest_in_release_window(CollectedMetric.objects.all(), self.release)

        self.assertEqual(latest, inside)

    def test_window_bounds_are_inclusive(self):
        at_start = self.collect(self.release.start_at)
        at_end = self.collect(self.release.end_at)

        qs = in_release_window(CollectedMetric.objects.all(), self.release)

        self.assertCountEqual(qs, [at_start, at_end])

    def test_latest_is_none_without_values_in_the_window(self):
        self.collect(self.now + timedelta(days=1))

        self.assertIsNone(latest_in_release_window(CollectedMetric.objects.all(), self.release))
