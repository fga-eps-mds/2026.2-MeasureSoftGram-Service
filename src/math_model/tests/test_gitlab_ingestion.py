from datetime import datetime

from django.contrib.auth import get_user_model
from django.utils import timezone
from freezegun import freeze_time
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from characteristics.models import CalculatedCharacteristic
from goals.models import Goal
from math_model.serializer import MetricsSerializer
from measures.models import CalculatedMeasure
from metrics.models import CollectedMetric
from organizations.models import RepositoryAccess
from release_configuration.models import ReleaseConfiguration
from releases.dashboard import get_release_repositories_tsqmi, get_release_summary
from releases.models import Release
from subcharacteristics.models import CalculatedSubCharacteristic
from tsqmi.models import TSQMI
from utils import staticfiles
from utils.tests import APITestCaseExpanded


def _aware_dt(*args):
    return timezone.make_aware(datetime(*args))


def _sonarqube_payload():
    return {
        "paging": {"pageIndex": 1, "pageSize": 500, "total": 5},
        "baseComponent": {"key": "grupo_projeto-gitlab"},
        "components": [
            {
                "qualifier": "FIL",
                "path": "src/service.py",
                "measures": [
                    {"metric": "coverage", "value": 85.0},
                    {"metric": "complexity", "value": 4},
                    {"metric": "functions", "value": 10},
                    {"metric": "comment_lines_density", "value": 25.0},
                    {"metric": "duplicated_lines_density", "value": 0.0},
                    {"metric": "sqale_debt_ratio", "value": 2.0},
                    {"metric": "ncloc", "value": 120},
                ],
            },
            {
                "qualifier": "FIL",
                "path": "src/views.py",
                "measures": [
                    {"metric": "coverage", "value": 75.0},
                    {"metric": "complexity", "value": 6},
                    {"metric": "functions", "value": 12},
                    {"metric": "comment_lines_density", "value": 20.0},
                    {"metric": "duplicated_lines_density", "value": 3.0},
                    {"metric": "sqale_debt_ratio", "value": 4.0},
                    {"metric": "ncloc", "value": 180},
                ],
            },
            {
                "qualifier": "UTS",
                "path": "tests/test_service.py",
                "measures": [
                    {"metric": "tests", "value": 6},
                    {"metric": "test_execution_time", "value": 90},
                ],
            },
            {
                "qualifier": "UTS",
                "path": "tests/test_views.py",
                "measures": [
                    {"metric": "tests", "value": 4},
                    {"metric": "test_execution_time", "value": 70},
                ],
            },
            {
                "qualifier": "TRK",
                "path": "",
                "measures": [
                    {"metric": "test_failures", "value": 0},
                    {"metric": "test_errors", "value": 0},
                ],
            },
        ],
    }


def _process_metrics_block():
    return {
        "metrics": [
            {"name": "total_issues", "value": 12, "path": "grupo/projeto-gitlab"},
            {"name": "resolved_issues", "value": 9, "path": "grupo/projeto-gitlab"},
            {"name": "sum_ci_feedback_times", "value": 240, "path": "grupo/projeto-gitlab"},
            {"name": "total_builds", "value": 4, "path": "grupo/projeto-gitlab"},
        ]
    }


def _gitlab_full_payload():
    return {
        "gitlab": _process_metrics_block(),
        "sonarqube": _sonarqube_payload(),
    }


def _github_full_payload():
    return {
        "github": _process_metrics_block(),
        "sonarqube": _sonarqube_payload(),
    }


@freeze_time("2026-11-10 15:00:00")
class GitLabMetricsIngestionTest(APITestCaseExpanded):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="gitlab-pipeline-user", password="test-password")
        self.token = Token.objects.create(user=self.user)

        self.org = self.get_organization(name="grupo-gitlab")
        self.org.gitlab_group_id = 4242
        self.org.save(update_fields=["gitlab_group_id"])

        self.product = self.get_product(self.org, name="Produto GitLab")
        self.repository = self.product.repositories.create(
            name="projeto-gitlab",
            description="Repositório importado do GitLab",
            platform="gitlab",
            imported=True,
            gitlab_project_id=98765,
            gitlab_path_with_namespace="grupo-gitlab/projeto-gitlab",
            url="https://gitlab.com/grupo-gitlab/projeto-gitlab",
        )

        ReleaseConfiguration.objects.get_or_create(
            name="Default pre-config",
            data=staticfiles.DEFAULT_PRE_CONFIG,
            product=self.product,
        )
        self.release_config = self.product.release_configuration.first()

        self.goal = Goal.objects.create(
            created_by=self.user,
            product=self.product,
            data={"reliability": 70, "maintainability": 60, "functional_suitability": 50},
        )
        self.release = Release.objects.create(
            release_name="Release 3 GitLab",
            start_at=_aware_dt(2026, 11, 1, 0, 0, 0),
            end_at=_aware_dt(2026, 11, 30, 23, 59, 59),
            created_by=self.user,
            product=self.product,
            goal=self.goal,
        )
        self.release.repositories.add(self.repository)

        self.url = (
            f"/api/v1/organizations/{self.org.id}"
            f"/products/{self.product.id}"
            f"/repositories/{self.repository.id}"
            f"/calculate/math-model/"
        )

    def _auth_client(self, token_key: str) -> APIClient:
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Token {token_key}")
        return client

    def test_metrics_serializer_accepts_gitlab_and_optional_blocks(self):
        serializer_gitlab = MetricsSerializer(data=_gitlab_full_payload())
        assert serializer_gitlab.is_valid(), serializer_gitlab.errors

        serializer_sonar_only = MetricsSerializer(data={"sonarqube": _sonarqube_payload()})
        assert serializer_sonar_only.is_valid(), serializer_sonar_only.errors

    def test_ingestao_gitlab_completa_persiste_camadas_e_associa_a_release(self):
        client = self._auth_client(self.token.key)
        response = client.post(self.url, _gitlab_full_payload(), format="json")

        assert response.status_code == status.HTTP_201_CREATED, response.content
        body = response.json()
        assert body["tsqmi"]["value"] > 0

        # Verifica persistência no banco vinculada ao repositório GitLab
        assert CollectedMetric.objects.filter(repository=self.repository).count() == 24
        measure_keys = set(
            CalculatedMeasure.objects.filter(repository=self.repository).values_list("measure__key", flat=True)
        )
        assert "team_throughput" in measure_keys
        assert "ci_feedback_time" in measure_keys
        assert "technical_debt_ratio" in measure_keys
        assert len(measure_keys) == 9

        assert CalculatedSubCharacteristic.objects.filter(repository=self.repository).count() == 4
        char_keys = set(
            CalculatedCharacteristic.objects.filter(repository=self.repository).values_list(
                "characteristic__key", flat=True
            )
        )
        assert char_keys == {"reliability", "maintainability", "functional_suitability"}
        assert TSQMI.objects.filter(repository=self.repository).count() == 1

        # Verifica associação automática com a Release ativa
        summary = get_release_summary(self.release, self.release_config)
        assert summary["totals"]["repositories"] == 1
        assert summary["totals"]["files"] == 2

        repos_tsqmi = get_release_repositories_tsqmi(self.release)["repositories"]
        assert len(repos_tsqmi) == 1
        assert repos_tsqmi[0]["id"] == self.repository.id
        assert repos_tsqmi[0]["tsqmi"]["value"] == body["tsqmi"]["value"]

    def test_paridade_entre_chaves_gitlab_e_github_no_payload(self):
        client = self._auth_client(self.token.key)
        resp_gitlab = client.post(self.url, _gitlab_full_payload(), format="json")
        assert resp_gitlab.status_code == status.HTTP_201_CREATED

        repo_gh = self.product.repositories.create(
            name="projeto-github-equivalente",
            platform="github",
        )
        url_gh = (
            f"/api/v1/organizations/{self.org.id}"
            f"/products/{self.product.id}"
            f"/repositories/{repo_gh.id}"
            f"/calculate/math-model/"
        )
        resp_github = client.post(url_gh, _github_full_payload(), format="json")
        assert resp_github.status_code == status.HTTP_201_CREATED

        gitlab_body = resp_gitlab.json()
        github_body = resp_github.json()

        assert gitlab_body["tsqmi"]["value"] == github_body["tsqmi"]["value"]
        gitlab_measures = {m["measure_id"]: m["value"] for m in gitlab_body["measures"]}
        github_measures = {m["measure_id"]: m["value"] for m in github_body["measures"]}
        assert gitlab_measures == github_measures

    def test_ingestao_sem_metricas_de_processo_gitlab_calcula_sonarqube(self):
        """Simula collectGitlabMetrics=false (payload contendo apenas sonarqube)."""
        client = self._auth_client(self.token.key)
        payload = {"sonarqube": _sonarqube_payload()}

        response = client.post(self.url, payload, format="json")
        assert response.status_code == status.HTTP_201_CREATED, response.content

        body = response.json()
        measure_keys = set(
            CalculatedMeasure.objects.filter(repository=self.repository).values_list("measure__key", flat=True)
        )
        assert "test_coverage" in measure_keys
        assert "technical_debt_ratio" in measure_keys
        assert "team_throughput" not in measure_keys

        char_keys = set(
            CalculatedCharacteristic.objects.filter(repository=self.repository).values_list(
                "characteristic__key", flat=True
            )
        )
        assert "reliability" in char_keys
        assert "maintainability" in char_keys
        assert body["tsqmi"]["value"] > 0

    def test_rejeita_chamada_sem_token_ou_com_token_invalido(self):
        unauth_client = APIClient()
        resp_no_token = unauth_client.post(self.url, _gitlab_full_payload(), format="json")
        assert resp_no_token.status_code == status.HTTP_401_UNAUTHORIZED

        invalid_client = self._auth_client("token-inexistente-123")
        resp_bad_token = invalid_client.post(self.url, _gitlab_full_payload(), format="json")
        assert resp_bad_token.status_code == status.HTTP_401_UNAUTHORIZED

    def test_rejeita_escrita_de_usuario_nao_membro_da_organizacao_gitlab(self):
        User = get_user_model()
        outsider = User.objects.create_user(username="outsider-gitlab", password="test-password")
        outsider_token = Token.objects.create(user=outsider)
        RepositoryAccess.objects.create(user=outsider, repository=self.repository)

        outsider_client = self._auth_client(outsider_token.key)
        response = outsider_client.post(self.url, _gitlab_full_payload(), format="json")
        assert response.status_code in (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND)
        assert TSQMI.objects.filter(repository=self.repository).count() == 0
