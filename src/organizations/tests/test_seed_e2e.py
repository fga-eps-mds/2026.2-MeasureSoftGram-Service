from io import StringIO

from django.core.management import call_command
from django.test import TransactionTestCase
from django.urls import reverse
from rest_framework.test import APIClient

from characteristics.models import CalculatedCharacteristic
from measures.models import CalculatedMeasure
from metrics.models import CollectedMetric
from organizations.management.commands.seed_e2e import ANALYSIS_DAYS_AGO, VALUES
from organizations.models import Organization
from releases.models import Release
from subcharacteristics.models import CalculatedSubCharacteristic
from tsqmi.models import TSQMI


class SeedE2ETestCase(TransactionTestCase):
    """TransactionTestCase: o load_initial_data engole IntegrityError, o que só funciona em autocommit."""

    def run_seed(self):
        call_command("seed_e2e", stdout=StringIO())

    def repository(self):
        organization = Organization.objects.get(key="e2e-org")
        return organization.products.get(name="E2E Produto").repositories.get(name="e2e-repo")

    def snapshot(self, repository):
        """Valores do repositório por data, sem ids: duas rodadas do seed devem dar o mesmo."""
        return {
            "tsqmi": list(TSQMI.objects.filter(repository=repository).order_by("created_at").values_list("value")),
            "characteristics": sorted(
                CalculatedCharacteristic.objects.filter(repository=repository).values_list(
                    "characteristic__key", "created_at", "value"
                )
            ),
            "subcharacteristics": CalculatedSubCharacteristic.objects.filter(repository=repository).count(),
            "measures": CalculatedMeasure.objects.filter(repository=repository).count(),
            "metrics": sorted(
                CollectedMetric.objects.filter(repository=repository).values_list("metric__key", "created_at", "value")
            ),
        }

    def test_creates_fixed_data_and_is_idempotent(self):
        self.run_seed()
        repository = self.repository()
        first = self.snapshot(repository)

        self.assertEqual([value for (value,) in first["tsqmi"]], list(VALUES["tsqmi"]))
        latest = {
            key: value
            for key, _, value in CalculatedCharacteristic.objects.filter(repository=repository)
            .order_by("created_at")
            .values_list("characteristic__key", "created_at", "value")
        }
        self.assertEqual(
            latest, {key: VALUES[key][-1] for key in ("reliability", "maintainability", "functional_suitability")}
        )
        self.assertEqual(len(first["characteristics"]), 3 * len(ANALYSIS_DAYS_AGO))
        self.assertGreater(first["subcharacteristics"], 0)
        self.assertGreater(first["measures"], 0)
        self.assertTrue(first["metrics"])

        self.run_seed()

        self.assertEqual(self.snapshot(self.repository()), first)
        self.assertEqual(Organization.objects.filter(key="e2e-org").count(), 1)
        release = Release.objects.get(product=repository.product)
        self.assertEqual(release.release_name, "E2E Release 1")
        self.assertLess(release.start_at, release.end_at)
        self.assertEqual(list(release.repositories.all()), [repository])

    def test_user_logs_in_with_password_and_is_member(self):
        self.run_seed()

        response = APIClient().post(
            reverse("accounts-login"), {"username": "e2e", "password": "e2e-senha"}, format="json"
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(Organization.objects.get(key="e2e-org").members.filter(username="e2e").exists())
