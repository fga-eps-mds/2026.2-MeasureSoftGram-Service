from io import StringIO
from unittest.mock import patch
from urllib.error import URLError

from django.contrib.auth import get_user_model
from django.core.management import call_command

from characteristics.models import CalculatedCharacteristic
from metrics.models import CollectedMetric
from tsqmi.models import TSQMI
from utils.tests import APITestCaseExpanded

COMMAND = "seed_grafana"


class SeedDemoDataTestCase(APITestCaseExpanded):
    def setUp(self):
        get_user_model().objects.create_superuser(username="admin", email="admin@example.com", password="admin")
        self.org = self.get_organization(add_user=False)
        self.product = self.get_product(self.org)
        self.repository = self.get_repository(self.product, name="2022-1-MeasureSoftGram-Service")

    def run_seed(self, **options):
        out, err = StringIO(), StringIO()
        call_command(COMMAND, days=2, repos=self.repository.name, stdout=out, stderr=err, **options)
        return out.getvalue() + err.getvalue()

    @patch("urllib.request.urlopen", side_effect=URLError("rede bloqueada no teste"))
    def test_seeds_demo_data_without_calling_grafana(self, urlopen):
        output = self.run_seed()

        urlopen.assert_not_called()
        self.assertNotIn("Grafana", output)
        self.assertTrue(CollectedMetric.objects.filter(repository=self.repository).exists())
        self.assertTrue(CalculatedCharacteristic.objects.filter(repository=self.repository).exists())
        self.assertTrue(TSQMI.objects.filter(repository=self.repository).exists())

    def test_rejects_grafana_options(self):
        with self.assertRaises(TypeError):
            self.run_seed(grafana_url="http://grafana:3000")
