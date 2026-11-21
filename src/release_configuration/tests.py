from core.ahp import CR_THRESHOLD, SAATY_PHRASES, SAATY_SCALE, calculate_group
from rest_framework.authtoken.models import Token
from rest_framework.mixins import status
from rest_framework.test import APIClient
from rest_framework.viewsets import reverse

from release_configuration.models import ReleaseConfiguration, ReleaseConfigurationComparison
from utils import staticfiles
from utils.tests import APITestCaseExpanded

# Create your tests here.


def _get_product_detail(*args):
    return reverse("product-detail", args=args)


class TestUnauthenticatedConfigEndpoints(APITestCaseExpanded):
    def setUp(self):
        self.request = APIClient()
        self.org = self.get_organization()
        self.prod = self.get_product(self.org)

    def test_that_unauthorized_is_prohibited(self):
        response = self.request.get(_get_product_detail(self.org.id, self.prod.id))
        self.assertIsNotNone(self.org.id)
        self.assertIsNotNone(self.prod.id)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class TestConfigEnpoints(APITestCaseExpanded):
    def setUp(self):
        self.request = APIClient()
        self.user = self.get_or_create_test_user()
        self.token = Token.objects.create(user=self.user)
        self.request.force_authenticate(user=self.user, token=self.token)
        self.org = self.get_organization()
        self.prod = self.get_product(self.org)

    def test_user_not_created_configs(self):
        detail_items = self.request.get(_get_product_detail(self.org.id, self.prod.id))
        pre_config_uri = detail_items.json()["actions"]
        self.assertIsNotNone(pre_config_uri)

        configs_resp = self.request.get(pre_config_uri["get current release-config"])

        self.assertEqual(configs_resp.status_code, status.HTTP_200_OK)
        self.assertFalse(configs_resp.json()["created_config"])

    def test_user_created_configs(self):
        detail_items = self.request.get(_get_product_detail(self.org.id, self.prod.id))
        pre_config_uri = detail_items.json()["actions"]

        measures = [
            {
                "key": "passed_tests",
                "weight": 100,
                "min_threshold": 0,
                "max_threshold": 1,
            }
        ]
        subcharacteristics = [{"key": "testing_status", "weight": 100, "measures": measures}]
        characteristics = [
            {
                "key": "reliability",
                "weight": 100,
                "subcharacteristics": subcharacteristics,
            }
        ]

        data = {
            "name": "Test release-config",
            "data": {"characteristics": characteristics},
        }
        response = self.request.post(pre_config_uri["create a new release-config"], data, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        configs_resp = self.request.get(pre_config_uri["get current release-config"])

        self.assertIn(
            dict(
                filter(
                    lambda item_tuple: item_tuple[0] == "id",
                    configs_resp.json().items(),
                )
            ),
            ReleaseConfiguration.objects.values("id").filter(id=configs_resp.json()["id"]),
        )
        self.assertEqual(configs_resp.status_code, status.HTTP_200_OK)
        self.assertTrue(configs_resp.json()["created_config"])

    def test_default_pre_config_returns_the_default_characteristics(self):
        url = reverse(
            "default-pre-config-list",
            kwargs={"organization_pk": self.org.id, "product_pk": self.prod.id},
        )

        response = self.request.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), staticfiles.DEFAULT_PRE_CONFIG)


class TestReleaseConfigurationImmutability(APITestCaseExpanded):
    def setUp(self):
        self.user = self.get_or_create_test_user()
        self.org = self.get_organization()
        self.prod = self.get_product(self.org)
        # Product.save() cria automaticamente uma release-config default
        self.config = self.prod.release_configuration.first()

    def test_that_queryset_update_is_prohibited(self):
        self.assertIsNotNone(self.config)
        with self.assertRaises(ValueError):
            ReleaseConfiguration.objects.filter(pk=self.config.pk).update(data={"hacked": True})

    def test_that_reverse_manager_update_is_prohibited(self):
        with self.assertRaises(ValueError):
            self.prod.release_configuration.filter(pk=self.config.pk).update(data={"hacked": True})

    def test_that_bulk_update_is_prohibited(self):
        self.config.data = {"hacked": True}
        with self.assertRaises(ValueError):
            ReleaseConfiguration.objects.bulk_update([self.config], ["data"])


class TestAHPScaleAndCalculateEndpoints(APITestCaseExpanded):
    def setUp(self):
        self.request = APIClient()
        self.user = self.get_or_create_test_user()
        self.token = Token.objects.create(user=self.user)
        self.request.force_authenticate(user=self.user, token=self.token)
        self.org = self.get_organization()
        self.prod = self.get_product(self.org)
        self.scale_url = reverse(
            "ahp-scale-list",
            kwargs={"organization_pk": self.org.id, "product_pk": self.prod.id},
        )
        self.calculate_url = reverse(
            "ahp-calculate-list",
            kwargs={"organization_pk": self.org.id, "product_pk": self.prod.id},
        )

    def test_ahp_scale_endpoint_returns_core_saaty_scale_and_threshold(self):
        response = self.request.get(self.scale_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertEqual(body["scale"], SAATY_SCALE)
        self.assertEqual(body["phrases"], SAATY_PHRASES)
        self.assertEqual(body["cr_threshold"], CR_THRESHOLD)

    def test_ahp_scale_requires_authentication(self):
        unauth_client = APIClient()
        response = unauth_client.get(self.scale_url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_ahp_calculate_reference_vectors_and_cli_parity(self):
        initial_configs = ReleaseConfiguration.objects.count()
        initial_comparisons = ReleaseConfigurationComparison.objects.count()

        vectors = [
            (
                ["a", "b"],
                [{"a": "a", "b": "b", "preferred": "a", "intensity": "muito_fortemente"}],
                {"a": 88, "b": 12},
                None,
                True,
            ),
            (
                ["a", "b"],
                [{"a": "a", "b": "b", "preferred": "a", "intensity": "fortemente"}],
                {"a": 83, "b": 17},
                None,
                True,
            ),
            (
                ["reliability", "maintainability", "functional_suitability"],
                [
                    {
                        "a": "reliability",
                        "b": "maintainability",
                        "preferred": None,
                        "intensity": "igual",
                    },
                    {
                        "a": "reliability",
                        "b": "functional_suitability",
                        "preferred": "reliability",
                        "intensity": "moderadamente",
                    },
                    {
                        "a": "maintainability",
                        "b": "functional_suitability",
                        "preferred": "maintainability",
                        "intensity": "moderadamente",
                    },
                ],
                {"reliability": 43, "maintainability": 43, "functional_suitability": 14},
                0.0,
                True,
            ),
            (
                ["passed_tests", "test_builds", "test_coverage"],
                [
                    {
                        "a": "passed_tests",
                        "b": "test_builds",
                        "preferred": "passed_tests",
                        "intensity": "muito_fortemente",
                    },
                    {
                        "a": "passed_tests",
                        "b": "test_coverage",
                        "preferred": "passed_tests",
                        "intensity": "moderadamente",
                    },
                    {
                        "a": "test_builds",
                        "b": "test_coverage",
                        "preferred": "test_coverage",
                        "intensity": "fortemente",
                    },
                ],
                {"passed_tests": 65, "test_builds": 7, "test_coverage": 28},
                0.0624,
                True,
            ),
            (
                ["a", "b", "c"],
                [
                    {"a": "a", "b": "b", "preferred": "a", "intensity": "muito_fortemente"},
                    {"a": "a", "b": "c", "preferred": "c", "intensity": "muito_fortemente"},
                    {"a": "b", "b": "c", "preferred": "b", "intensity": "muito_fortemente"},
                ],
                {"a": 34, "b": 33, "c": 33},
                4.9451,
                False,
            ),
        ]

        for entities, answers, expected_weights, expected_cr, expected_consistent in vectors:
            with self.subTest(entities=entities, expected_weights=expected_weights):
                response = self.request.post(
                    self.calculate_url,
                    {"entities": entities, "answers": answers},
                    format="json",
                )
                self.assertEqual(response.status_code, status.HTTP_200_OK)
                body = response.json()
                self.assertEqual(body["weights"], expected_weights)
                self.assertEqual(list(body["weights"].keys()), entities)
                self.assertEqual(body["consistent"], expected_consistent)
                self.assertEqual(body["cr_threshold"], CR_THRESHOLD)

                if expected_cr is None:
                    self.assertIsNone(body["consistency_ratio"])
                else:
                    self.assertAlmostEqual(body["consistency_ratio"], expected_cr, places=3)

                core_result = calculate_group(
                    entities,
                    [(item["a"], item["b"], item["preferred"], item["intensity"]) for item in answers],
                )
                self.assertEqual(body["weights"], core_result.weights)
                self.assertEqual(body["priorities"], core_result.priorities)

        self.assertEqual(ReleaseConfiguration.objects.count(), initial_configs)
        self.assertEqual(ReleaseConfigurationComparison.objects.count(), initial_comparisons)

    def test_ahp_calculate_single_entity_group_returns_100_without_answers(self):
        response = self.request.post(
            self.calculate_url,
            {"entities": ["modifiability"], "answers": []},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertEqual(body["weights"], {"modifiability": 100})
        self.assertEqual(body["priorities"], {"modifiability": 1.0})
        self.assertIsNone(body["consistency_ratio"])
        self.assertTrue(body["consistent"])
        self.assertIsNone(body["conflict"])

    def test_ahp_calculate_four_entities_with_conflict_returns_conflict_diagnosis(self):
        entities = ["m1", "m2", "m3", "m4"]
        answers = [
            {"a": "m1", "b": "m2", "preferred": "m1", "intensity": "moderadamente"},
            {"a": "m1", "b": "m3", "preferred": "m1", "intensity": "moderadamente"},
            {"a": "m1", "b": "m4", "preferred": "m4", "intensity": "extremamente"},
            {"a": "m2", "b": "m3", "preferred": None, "intensity": "igual"},
            {"a": "m2", "b": "m4", "preferred": "m2", "intensity": "moderadamente"},
            {"a": "m3", "b": "m4", "preferred": "m3", "intensity": "moderadamente"},
        ]
        response = self.request.post(
            self.calculate_url,
            {"entities": entities, "answers": answers},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertFalse(body["consistent"])
        self.assertIsNotNone(body["conflict"])
        self.assertEqual(body["conflict"]["a"], "m1")
        self.assertEqual(body["conflict"]["b"], "m4")

    def test_ahp_calculate_rejects_missing_pairs_or_invalid_intensity(self):
        missing_pair_resp = self.request.post(
            self.calculate_url,
            {
                "entities": ["a", "b", "c"],
                "answers": [{"a": "a", "b": "b", "preferred": None, "intensity": "igual"}],
            },
            format="json",
        )
        self.assertEqual(missing_pair_resp.status_code, status.HTTP_400_BAD_REQUEST)

        invalid_intensity_resp = self.request.post(
            self.calculate_url,
            {
                "entities": ["a", "b"],
                "answers": [{"a": "a", "b": "b", "preferred": "a", "intensity": "invalida"}],
            },
            format="json",
        )
        self.assertEqual(invalid_intensity_resp.status_code, status.HTTP_400_BAD_REQUEST)
