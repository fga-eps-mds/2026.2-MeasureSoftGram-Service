from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient, APITestCase

from organizations.models import Organization


def _page(body, headers=None, links=None):
    resp = MagicMock()
    resp.status_code = 200
    resp.headers = headers or {}
    resp.links = links or {}
    resp.content = b"{}"
    resp.json.return_value = body
    return resp


class ProviderListingTestCase(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="dev", password="pass")
        self.user.github_access_token = "gh"
        self.user.gitlab_access_token = "gl"
        self.user.save()
        self.org = Organization.objects.create(name="Dev", github_org_name="dev")
        self.org.members.add(self.user)
        self.client = APIClient()
        self.client.force_authenticate(self.user, token=Token.objects.create(user=self.user))

    @patch("accounts.views.requests.get")
    def test_gitlab_groups_follow_every_page(self, mock_get):
        def side_effect(url, headers=None, timeout=None):
            if "api/v4/user" in url:
                return _page({"id": 1, "username": "dev"})
            if "page=2" in url:
                return _page([{"id": 2, "name": "G2", "full_path": "g2"}])
            return _page([{"id": 1, "name": "G1", "full_path": "g1"}], headers={"X-Next-Page": "2"})

        mock_get.side_effect = side_effect

        response = self.client.get(reverse("gitlab-namespaces"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["id"] for item in response.json()], [1, 1, 2])
        group_urls = [c[0][0] for c in mock_get.call_args_list if "/groups" in c[0][0]]
        self.assertTrue(all("min_access_level=10" in url and "per_page=100" in url for url in group_urls))

    @patch("organizations.views.requests.get")
    def test_gitlab_personal_space_lists_member_projects(self, mock_get):
        mock_get.return_value = _page([{"id": 5, "name": "p", "path_with_namespace": "x/p", "web_url": "u"}])

        url = reverse("gitlab-projects-list", kwargs={"organization_pk": self.org.id})
        response = self.client.get(url, {"namespace_id": 1, "kind": "user", "search": "p"})

        self.assertEqual(response.status_code, 200)
        args, kwargs = mock_get.call_args
        self.assertEqual(args[0], "https://gitlab.com/api/v4/projects")
        self.assertEqual(kwargs["params"]["membership"], "true")
        self.assertEqual(kwargs["params"]["per_page"], 10)
        self.assertEqual(kwargs["params"]["search"], "p")

    @patch("organizations.utils.requests.get")
    def test_github_personal_search_finds_collaborator_repo_on_second_page(self, mock_get):
        first = [{"id": 1, "name": "alpha", "full_name": "me/alpha", "html_url": "u1"}]
        second = [{"id": 2, "name": "msg-collab", "full_name": "other/msg-collab", "html_url": "u2"}]

        def side_effect(url, headers=None, params=None, timeout=None):
            if params is None:
                return _page(second)
            return _page(first, links={"next": {"url": "https://api.github.com/user/repos?page=2"}})

        mock_get.side_effect = side_effect

        url = reverse("github-repos-list", kwargs={"organization_pk": self.org.id})
        response = self.client.get(url, {"search": "MSG"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual([r["github_full_name"] for r in response.json()], ["other/msg-collab"])
        self.assertEqual(response["X-Total-Pages"], "1")
        self.assertNotIn("X-Next-Page", response)
