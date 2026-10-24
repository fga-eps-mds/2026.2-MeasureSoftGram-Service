import logging

import requests

logger = logging.getLogger(__name__)


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
        logger.warning(
            f"No GitHub Actions triggered for {repository.name}. "
            "The repository stays without metrics until the first real collection."
        )
