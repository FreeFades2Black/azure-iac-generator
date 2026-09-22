import os
import subprocess
from app.models.schemas import InfrastructureBuildRequest

def push_to_github(build_dir: str, request: InfrastructureBuildRequest, token: str | None = None) -> str:
    """
    Initializes git repository in build_dir, commits all rendered artifacts,
    and publishes to the designated GitHub repository using token authentication.
    Masks credentials in case of any git execution errors.
    """
    auth_token = token or os.environ.get("GITHUB_TOKEN")
    if not auth_token:
        raise RuntimeError("GITHUB_TOKEN environment variable is not configured")

    remote_url = f"https://x-access-token:{auth_token}@github.com/{request.github_org_or_user}/{request.github_repo_name}.git"

    commands = [
        ["git", "init", "-b", "main"],
        ["git", "config", "user.name", "Antigravity-IaC-Bot"],
        ["git", "config", "user.email", "bot@local.omarchy"],
        ["git", "add", "."],
        ["git", "commit", "-m", f"Initial automated release for {request.project_name} ({request.redundancy.value})"],
        ["git", "remote", "add", "origin", remote_url],
        ["git", "push", "-u", "origin", "main", "--force"]
    ]

    for cmd in commands:
        res = subprocess.run(cmd, cwd=build_dir, capture_output=True, text=True)
        if res.returncode != 0:
            # Scrub token from error message to avoid security exposure
            safe_err = res.stderr.replace(auth_token, "********")
            cmd_display = " ".join([c if auth_token not in c else "remote_url" for c in cmd])
            raise RuntimeError(f"Git execution failed on '{cmd_display}': {safe_err}")

    return f"https://github.com/{request.github_org_or_user}/{request.github_repo_name}"
