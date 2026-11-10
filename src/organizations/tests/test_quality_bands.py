from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.reverse import reverse
from rest_framework.test import APIClient

from organizations.models import Product
from utils.tests import APITestCaseExpanded

User = get_user_model()

DEFAULT_BANDS = [
    {"key": "E", "min": 0.0, "max": 0.2},
    {"key": "D", "min": 0.2, "max": 0.4},
    {"key": "C", "min": 0.4, "max": 0.6},
    {"key": "B", "min": 0.6, "max": 0.8},
    {"key": "A", "min": 0.8, "max": 1.0},
]


def bands_from(*limits):
    """As 5 faixas de E a A a partir dos 4 cortes, como o Front envia."""
    edges = (0, *limits, 1)
    return [{"key": key, "min": edges[index], "max": edges[index + 1]} for index, key in enumerate("EDCBA")]


class QualityBandsTestCase(APITestCaseExpanded):
    def setUp(self):
        self.user = self.get_or_create_test_user()
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.org = self.get_organization()
        self.product = self.get_product(self.org)
        self.url = reverse("product-quality-bands", args=[self.org.id, self.product.id])

    def as_member(self, username="member"):
        """Autentica um membro da organização que não é o administrador."""
        member = User.objects.create(username=username, email=f"{username}@email.com")
        self.org.members.add(member)
        self.client.force_authenticate(member)
        return member

    def as_outsider(self):
        outsider = User.objects.create(username="outsider", email="outsider@email.com")
        self.client.force_authenticate(outsider)
        return outsider

    def put(self, bands):
        return self.client.put(self.url, {"bands": bands}, format="json")

    def saved_limits(self):
        return Product.objects.get(id=self.product.id).quality_band_limits


class QualityBandsReadTests(QualityBandsTestCase):
    def test_unauthenticated_not_allowed(self):
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get(self.url).status_code, status.HTTP_401_UNAUTHORIZED)

    def test_product_never_changed_returns_default_bands(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), {"is_default": True, "can_edit": True, "bands": DEFAULT_BANDS})

    def test_member_reads_but_cannot_edit(self):
        self.as_member()

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.json()["can_edit"])
        self.assertEqual(response.json()["bands"], DEFAULT_BANDS)

    def test_outsider_gets_404(self):
        self.as_outsider()
        self.assertEqual(self.client.get(self.url).status_code, status.HTTP_404_NOT_FOUND)

    def test_product_of_another_organization_gets_404(self):
        other_org = self.get_organization(name="Other Organization")
        url = reverse("product-quality-bands", args=[other_org.id, self.product.id])
        self.assertEqual(self.client.get(url).status_code, status.HTTP_404_NOT_FOUND)


class QualityBandsUpdateTests(QualityBandsTestCase):
    def test_admin_saves_new_limits(self):
        response = self.put(bands_from(0.2, 0.4, 0.7, 0.8))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.json()["is_default"])
        self.assertEqual(response.json()["bands"][2], {"key": "C", "min": 0.4, "max": 0.7})
        self.assertEqual(response.json()["bands"][3], {"key": "B", "min": 0.7, "max": 0.8})
        self.assertEqual(self.saved_limits(), ["0.20", "0.40", "0.70", "0.80"])

    def test_saved_limits_survive_a_new_read(self):
        self.put(bands_from(0.1, 0.3, 0.5, 0.9))

        response = self.client.get(self.url)

        self.assertEqual(response.json()["bands"], [
            {"key": "E", "min": 0.0, "max": 0.1},
            {"key": "D", "min": 0.1, "max": 0.3},
            {"key": "C", "min": 0.3, "max": 0.5},
            {"key": "B", "min": 0.5, "max": 0.9},
            {"key": "A", "min": 0.9, "max": 1.0},
        ])

    def test_default_limits_keep_the_product_on_defaults(self):
        self.put(bands_from(0.1, 0.3, 0.5, 0.9))

        response = self.put(bands_from("0.20", "0.40", "0.60", "0.80"))

        self.assertTrue(response.json()["is_default"])
        self.assertIsNone(self.saved_limits())

    def test_member_cannot_save(self):
        self.as_member()

        response = self.put(bands_from(0.2, 0.4, 0.7, 0.8))

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIsNone(self.saved_limits())

    def test_outsider_cannot_save(self):
        self.as_outsider()

        response = self.put(bands_from(0.2, 0.4, 0.7, 0.8))

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertIsNone(self.saved_limits())


class QualityBandsValidationTests(QualityBandsTestCase):
    def assert_rejected(self, bands, band, field, detail):
        response = self.put(bands)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn({"band": band, "field": field, "detail": detail}, response.json()["errors"])
        self.assertIsNone(self.saved_limits())

    def test_limit_equal_to_the_previous_one(self):
        self.assert_rejected(bands_from(0.2, 0.4, 0.4, 0.8), "C", "max", "O limite precisa ser maior que 0,40.")

    def test_limit_lower_than_the_previous_one(self):
        self.assert_rejected(bands_from(0.2, 0.5, 0.4, 0.8), "C", "max", "O limite precisa ser maior que 0,50.")

    def test_limit_out_of_range(self):
        self.assert_rejected(bands_from(0.2, 0.4, 0.6, 1.5), "B", "max", "Use um valor entre 0 e 1.")

    def test_negative_limit(self):
        self.assert_rejected(bands_from(-0.1, 0.4, 0.6, 0.8), "E", "max", "Use um valor entre 0 e 1.")

    def test_last_limit_equal_to_one_leaves_band_a_empty(self):
        self.assert_rejected(bands_from(0.2, 0.4, 0.6, 1), "B", "max", "O limite precisa ser menor que 1,00.")

    def test_first_limit_equal_to_zero_leaves_band_e_empty(self):
        self.assert_rejected(bands_from(0, 0.4, 0.6, 0.8), "E", "max", "O limite precisa ser maior que 0,00.")

    def test_gap_between_bands(self):
        bands = bands_from(0.2, 0.4, 0.6, 0.8)
        bands[1]["min"] = 0.25
        self.assert_rejected(bands, "D", "min", "A faixa D começa onde a faixa E termina (0,20).")

    def test_overlap_between_bands(self):
        bands = bands_from(0.2, 0.4, 0.6, 0.8)
        bands[3]["min"] = 0.5
        self.assert_rejected(bands, "B", "min", "A faixa B começa onde a faixa C termina (0,60).")

    def test_first_band_starts_at_zero(self):
        bands = bands_from(0.2, 0.4, 0.6, 0.8)
        bands[0]["min"] = 0.1
        self.assert_rejected(bands, "E", "min", "A faixa E começa em 0.")

    def test_last_band_ends_at_one(self):
        bands = bands_from(0.2, 0.4, 0.6, 0.8)
        bands[4]["max"] = 0.9
        self.assert_rejected(bands, "A", "max", "A faixa A termina em 1.")

    def test_bands_out_of_order(self):
        bands = bands_from(0.2, 0.4, 0.6, 0.8)
        bands[0], bands[1] = bands[1], bands[0]
        self.assert_rejected(bands, None, "key", "Envie as 5 faixas na ordem E, D, C, B e A.")

    def test_missing_band(self):
        bands = bands_from(0.2, 0.4, 0.6, 0.8)[:4]
        self.assert_rejected(bands, None, "key", "Envie as 5 faixas na ordem E, D, C, B e A.")

    def test_more_than_two_decimal_places(self):
        self.assert_rejected(bands_from(0.2, 0.4, 0.655, 0.8), "C", "max", "Use no máximo duas casas decimais.")

    def test_limit_that_is_not_a_number(self):
        self.assert_rejected(bands_from(0.2, "abc", 0.6, 0.8), "D", "max", "Use um número entre 0 e 1.")

    def test_body_without_bands(self):
        response = self.client.put(self.url, {}, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["errors"][0]["field"], "bands")

    def test_bands_that_are_not_a_list(self):
        for payload in ("0.2,0.4", {"E": 0.2}, ["0.2"]):
            with self.subTest(payload=payload):
                response = self.client.put(self.url, {"bands": payload}, format="json")

                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
                self.assertEqual(response.json()["errors"][0]["field"], "bands")
                self.assertIsNone(self.saved_limits())


class QualityBandsRestoreTests(QualityBandsTestCase):
    def test_admin_restores_defaults(self):
        self.put(bands_from(0.1, 0.3, 0.5, 0.9))

        response = self.client.delete(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), {"is_default": True, "can_edit": True, "bands": DEFAULT_BANDS})
        self.assertIsNone(self.saved_limits())

    def test_member_cannot_restore(self):
        self.put(bands_from(0.1, 0.3, 0.5, 0.9))
        self.as_member()

        response = self.client.delete(self.url)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(self.saved_limits(), ["0.10", "0.30", "0.50", "0.90"])
