import logging
from urllib.parse import parse_qs, urlparse

import requests

from math_model.services import MathModelServices
from math_model.utils import parse_release_configuration
from release_configuration.models import ReleaseConfiguration
from release_configuration.serializers import ReleaseConfigurationSerializer
from utils import staticfiles

logger = logging.getLogger(__name__)


def get_default_mock_payload():
    return {
        "github": {
            "metrics": [
                {"name": "total_issues", "value": 1},
                {"name": "resolved_issues", "value": 0},
                {"name": "sum_ci_feedback_times", "value": 1},
                {"name": "total_builds", "value": 1},
            ],
        },
        "sonarqube": {
            "components": [
                {
                    "qualifier": "FIL",
                    "path": "src/foo.py",
                    "measures": [
                        {"metric": "coverage", "value": 0.0},
                        {"metric": "complexity", "value": 1},
                        {"metric": "functions", "value": 1},
                        {"metric": "comment_lines_density", "value": 0.0},
                        {"metric": "duplicated_lines_density", "value": 0.0},
                        {"metric": "ncloc", "value": 1},
                    ],
                },
                {
                    "qualifier": "FIL",
                    "path": "src/bar.py",
                    "measures": [
                        {"metric": "coverage", "value": 0.0},
                        {"metric": "complexity", "value": 1},
                        {"metric": "functions", "value": 1},
                        {"metric": "comment_lines_density", "value": 0.0},
                        {"metric": "duplicated_lines_density", "value": 0.0},
                        {"metric": "ncloc", "value": 1},
                    ],
                },
                {
                    "qualifier": "UTS",
                    "path": "tests/foo_test.py",
                    "measures": [
                        {"metric": "tests", "value": 1},
                        {"metric": "test_execution_time", "value": 1},
                    ],
                },
                {
                    "qualifier": "UTS",
                    "path": "tests/bar_test.py",
                    "measures": [
                        {"metric": "tests", "value": 1},
                        {"metric": "test_execution_time", "value": 1},
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
        },
    }


def _trigger_github_workflow(repo_full_name, headers):
    url_workflows = f"https://api.github.com/repos/{repo_full_name}/actions/workflows"
    try:
        r = requests.get(url_workflows, headers=headers, timeout=10)
        if r.status_code != 200:
            return False

        data = r.json()
        workflows = data.get("workflows", [])
        if not workflows:
            return False

        selected_workflow = None
        for wf in workflows:
            name_lower = wf.get("name", "").lower()
            if "measure" in name_lower or "sonar" in name_lower:
                selected_workflow = wf
                break
        if not selected_workflow:
            selected_workflow = workflows[0]

        wf_id = selected_workflow["id"]

        r_repo = requests.get(
            f"https://api.github.com/repos/{repo_full_name}",
            headers=headers,
            timeout=10,
        )
        default_branch = "main"
        if r_repo.status_code == 200:
            default_branch = r_repo.json().get("default_branch", "main")

        url_trigger = f"https://api.github.com/repos/{repo_full_name}/actions/workflows/{wf_id}/dispatches"
        r_dispatch = requests.post(
            url_trigger,
            headers=headers,
            json={"ref": default_branch},
            timeout=10,
        )

        if r_dispatch.status_code == 204:
            logger.info(f"Successfully triggered workflow dispatch for {repo_full_name}")
            return True
    except Exception as exc:
        logger.error(f"Error checking/triggering GitHub Actions for {repo_full_name}: {exc}")
    return False


def onboard_repository_async(repository, user):
    token = getattr(user, "github_access_token", None)
    repo_full_name = repository.github_full_name

    has_triggered_workflow = False

    if token and repo_full_name:
        headers = {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json",
        }
        has_triggered_workflow = _trigger_github_workflow(repo_full_name, headers)

    if not has_triggered_workflow:
        logger.info(f"No GitHub Actions triggered. Generating mock metrics for {repository.name}...")
        try:
            product = repository.product
            release_configuration, _ = ReleaseConfiguration.objects.get_or_create(
                name="Default pre-config",
                product=product,
                defaults={
                    "data": staticfiles.DEFAULT_PRE_CONFIG,
                },
            )

            services = MathModelServices(repository, product)
            config_serializer = ReleaseConfigurationSerializer(release_configuration)
            char_keys, subchar_keys, measure_keys = parse_release_configuration(
                config_serializer.data,
            )

            mock_payload = get_default_mock_payload()
            collected_metrics = services.build_collected_metrics(mock_payload)
            measures, measure_values = services.build_calculated_measures(
                measure_keys,
                release_configuration,
                collected_metrics,
            )
            subchars, subchar_values = services.build_calculated_subcharacteristics(
                subchar_keys,
                release_configuration,
                measure_values,
            )
            chars, char_values = services.build_calculated_characteristics(
                char_keys,
                release_configuration,
                subchar_values,
            )
            tsqmi = services.build_tsqmi(release_configuration, char_values)

            services.persist_all(
                collected_metrics,
                measures,
                subchars,
                chars,
                tsqmi,
            )
            logger.info(f"Successfully populated mock math model calculations for {repository.name}")
        except Exception as exc:
            logger.error(f"Failed to populate mock calculations for {repository.name}: {exc}")


GITHUB_REPOS_PER_PAGE = 10
GITHUB_SEARCH_MAX_RESULTS = 1000
GITLAB_PROJECTS_PER_PAGE = 10


def github_link_page(links, rel):
    """Número da página apontada pelo `rel` do header Link do GitHub, ou None."""
    url = (links or {}).get(rel, {}).get("url")
    if not url:
        return None
    values = parse_qs(urlparse(url).query).get("page")
    return int(values[0]) if values and values[0].isdigit() else None


def github_total_pages(links, current_page):
    """Total de páginas: a do `rel="last"`; sem ele, a página atual é a última."""
    return github_link_page(links, "last") or current_page


def search_github_user_repos(headers, search, timeout):
    """
    Repositórios de `/user/repos` (dono e colaborador) cujo nome contém `search`, ordenados por nome.
    Percorre todas as páginas de 100; PermissionError se o token for recusado.
    """
    repos = []
    url = "https://api.github.com/user/repos"
    params = {"affiliation": "owner,collaborator", "sort": "full_name", "per_page": 100}
    while url:
        response = requests.get(url, headers=headers, params=params, timeout=timeout)
        if response.status_code in (401, 403):
            raise PermissionError("GitHub recusou o token.")
        if response.status_code != 200:
            break
        repos.extend(response.json())
        url = response.links.get("next", {}).get("url")
        params = None
    needle = search.lower()
    return [repo for repo in repos if needle in (repo.get("name") or "").lower()]


def _fetch_paginated(url, headers, params=None, timeout=10):
    """Itens de todas as páginas (header Link) de um endpoint de lista do GitHub/GitLab; None se alguma falhar."""
    items = []
    while url:
        response = requests.get(url, headers=headers, params=params, timeout=timeout)
        if response.status_code != 200:
            return None
        body = response.json()
        if not isinstance(body, list):
            return None
        items.extend(body)
        next_url = (response.links or {}).get("next", {}).get("url")
        url, params = next_url, None
    return items


def _sync_organization_membership(user, id_field, provider_ids):
    """Entra nas Organizations do provedor das quais o usuário faz parte e sai das que ele deixou."""
    from organizations.models import Organization

    linked = Organization.objects.filter(**{f"{id_field}__isnull": False})
    for org in linked.filter(**{f"{id_field}__in": provider_ids}).exclude(members=user):
        org.members.add(user)
    for org in linked.filter(members=user).exclude(**{f"{id_field}__in": provider_ids}):
        org.members.remove(user)


def _sync_repository_access(user, platform, repository_filter, provider_repos_found):
    from django.utils import timezone

    from organizations.models import Repository, RepositoryAccess

    repositories = Repository.objects.filter(platform=platform)
    allowed = repositories.filter(repository_filter).exclude(product__organization__members=user)
    for repository in allowed:
        RepositoryAccess.objects.update_or_create(
            user=user, repository=repository, defaults={"checked_at": timezone.now()}
        )
    if provider_repos_found:
        RepositoryAccess.objects.filter(user=user, repository__platform=platform).exclude(
            repository__in=allowed
        ).delete()


def _sync_github(user, timeout):
    from django.db.models import Q

    headers = {"Authorization": f"token {user.github_access_token}", "Accept": "application/json"}
    profile = requests.get("https://api.github.com/user", headers=headers, timeout=timeout)
    orgs = _fetch_paginated("https://api.github.com/user/orgs", headers, {"per_page": 100}, timeout)
    if profile.status_code == 200 and orgs is not None:
        ids = [profile.json().get("id")] + [org.get("id") for org in orgs]
        _sync_organization_membership(user, "github_org_id", [i for i in ids if i])

    collaborator = _fetch_paginated(
        "https://api.github.com/user/repos",
        headers,
        {"affiliation": "collaborator", "per_page": 100},
        timeout,
    )
    if collaborator is not None:
        ids = [repo.get("id") for repo in collaborator if repo.get("id")]
        names = [repo.get("full_name") for repo in collaborator if repo.get("full_name")]
        _sync_repository_access(
            user, "github", Q(github_repo_id__in=ids) | Q(github_full_name__in=names), True
        )


def _sync_gitlab(user, timeout):
    from django.db.models import Q

    headers = {"Authorization": f"Bearer {user.gitlab_access_token}", "Accept": "application/json"}
    base = "https://gitlab.com/api/v4"
    groups = _fetch_paginated(f"{base}/groups", headers, {"min_access_level": 10, "per_page": 100}, timeout)
    if groups is not None:
        _sync_organization_membership(user, "gitlab_group_id", [group.get("id") for group in groups])

    projects = _fetch_paginated(
        f"{base}/projects", headers, {"membership": "true", "simple": "true", "per_page": 100}, timeout
    )
    if projects is not None:
        ids = [project.get("id") for project in projects if project.get("id")]
        _sync_repository_access(user, "gitlab", Q(gitlab_project_id__in=ids), True)


def sync_provider_memberships(user):
    """
    Alinha o que o usuário vê no MSG ao que ele vê no GitHub/GitLab: entra/sai das Organizations
    vinculadas ao provedor e registra o acesso aos repositórios em que é só colaborador.
    Falhas do provedor são ignoradas, para nunca quebrar o login.
    """
    from django.conf import settings

    timeout = getattr(settings, "GITHUB_TIMEOUT", 10)
    syncs = (
        (user.github_access_token, _sync_github),
        (user.gitlab_access_token, _sync_gitlab),
    )
    for token, sync in syncs:
        if not token:
            continue
        try:
            sync(user, timeout)
        except Exception as exc:
            logger.warning("Falha ao sincronizar acessos do provedor para %s: %s", user, exc)
