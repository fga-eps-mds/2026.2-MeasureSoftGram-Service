from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import override_settings

from organizations.access import provider_grants_access
from organizations.models import Organization, Repository
from organizations.utils import sync_provider_memberships
from utils.tests import APITestCaseExpanded

FAKE_GITLAB = "http://fake-gitlab:8080"
FAKE_GITHUB = "http://fake-gitlab:8080/github"


def _ok(body=None):
    resp = MagicMock(status_code=200, links={}, headers={}, content=b"[]")
    resp.json.return_value = body if body is not None else []
    return resp


@override_settings(GITLAB_BASE_URL=FAKE_GITLAB, GITHUB_API_URL=FAKE_GITHUB)
class ProviderUrlsTestCase(APITestCaseExpanded):
    """As chamadas aos provedores usam GITLAB_BASE_URL e GITHUB_API_URL (o E2E aponta para um servidor falso)."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(username="u", password="p")
        self.user.github_access_token = "gh-tok"
        self.user.gitlab_access_token = "gl-tok"
        self.user.save()
        self.product = Organization.objects.create(name="Org").products.create(name="Prod")

    @patch("organizations.access.requests.get", return_value=_ok())
    def test_repository_access_check_uses_configured_urls(self, mock_get):
        github_repo = Repository.objects.create(
            name="gh", product=self.product, platform="github", github_full_name="org/gh"
        )
        gitlab_repo = Repository.objects.create(
            name="gl", product=self.product, platform="gitlab", gitlab_project_id=7
        )

        self.assertTrue(provider_grants_access(self.user, github_repo))
        self.assertTrue(provider_grants_access(self.user, gitlab_repo))

        urls = [call.args[0] for call in mock_get.call_args_list]
        self.assertEqual(urls, [f"{FAKE_GITHUB}/repos/org/gh", f"{FAKE_GITLAB}/api/v4/projects/7"])

    @patch("organizations.utils.requests.get", return_value=_ok())
    def test_membership_sync_uses_configured_urls(self, mock_get):
        sync_provider_memberships(self.user)

        urls = [call.args[0] for call in mock_get.call_args_list]
        self.assertIn(f"{FAKE_GITHUB}/user/orgs", urls)
        self.assertIn(f"{FAKE_GITLAB}/api/v4/groups", urls)
        self.assertFalse([url for url in urls if "github.com" in url or "gitlab.com" in url])

    def test_repository_url_on_configured_gitlab_host_fills_namespace(self):
        repo = Repository.objects.create(
            name="r", product=self.product, platform="gitlab", url=f"{FAKE_GITLAB}/grupo/sub/r"
        )

        self.assertEqual(repo.gitlab_path_with_namespace, "grupo/sub/r")
