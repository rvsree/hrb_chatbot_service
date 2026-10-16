"""Phase 183 - read-only GitHub Actions status for the Deployment
Dashboard's CI/Build Status tab. Plain HTTP (GitHub's REST API), no
official SDK - same pattern as tavily_client.py: never raises, an
"error" key on failure instead. GITHUB_TOKEN needs only read-only
actions:read scope - this client never triggers or cancels a run."""

import requests

from src.hrb_chatbot.common.config.settings import read_setting, read_url_setting
from src.hrb_chatbot.common.logging.logger import get_logger

logger = get_logger("github_actions_client")


class GitHubActionsClient:
    PROVIDER_NAME = "github_actions"
    ENV_KEY = "GITHUB_TOKEN"

    DEFAULT_BASE_URL = "https://api.github.com"
    DEFAULT_TIMEOUT_SECONDS = 15

    def __init__(self, token: str | None = None, repo: str | None = None, base_url: str | None = None):
        self.token = read_setting(token, "GITHUB_TOKEN")
        # "owner/repo", e.g. "rvsree/hrb_chatbot_v2" - this project's own
        # repo by default, never guessed for a different one.
        self.repo = read_setting(repo, "GITHUB_REPO", "rvsree/hrb_chatbot_v2")
        self.base_url = read_url_setting(base_url, "GITHUB_API_BASE_URL", self.DEFAULT_BASE_URL)

        if not self.token:
            logger.warning("[GITHUB_ACTIONS] GITHUB_TOKEN not set")

    def build_headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def list_workflow_runs(self, workflow_file: str, per_page: int = 5) -> dict:
        """Latest runs of one workflow file (e.g. "ci.yml"). Never raises -
        {"runs": [], "error": "..."} on any failure, including an unset
        token, matching the client-layer-returns-errors-as-data convention."""
        if not self.token:
            return {"runs": [], "error": "GITHUB_TOKEN not configured"}

        url = f"{self.base_url}/repos/{self.repo}/actions/workflows/{workflow_file}/runs"
        try:
            response = requests.get(
                url,
                headers=self.build_headers(),
                params={"per_page": per_page},
                timeout=self.DEFAULT_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            data = response.json()
        except Exception as error:
            logger.warning("[GITHUB_ACTIONS] Could not list runs for %s: %s", workflow_file, error)
            return {"runs": [], "error": str(error)}

        runs = [
            {
                "id": run["id"],
                "status": run["status"],
                "conclusion": run["conclusion"],
                "head_sha": run["head_sha"][:7],
                "head_commit_message": (run.get("head_commit") or {}).get("message", "").splitlines()[0]
                if (run.get("head_commit") or {}).get("message")
                else "",
                "html_url": run["html_url"],
                "created_at": run["created_at"],
            }
            for run in data.get("workflow_runs", [])
        ]
        return {"runs": runs, "error": None}

    def health_check(self) -> dict:
        result = {"provider": self.PROVIDER_NAME, "repo": self.repo, "base_url": self.base_url}

        if not self.token:
            result["status"] = "unhealthy"
            result["message"] = "GITHUB_TOKEN not configured"
            return result

        try:
            response = requests.get(f"{self.base_url}/repos/{self.repo}", headers=self.build_headers(), timeout=self.DEFAULT_TIMEOUT_SECONDS)
            response.raise_for_status()
            result["status"] = "healthy"
        except Exception as error:
            result["status"] = "unhealthy"
            result["message"] = str(error)

        return result
