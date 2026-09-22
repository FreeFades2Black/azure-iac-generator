import os
import shutil
import subprocess
from pathlib import Path

class PipelineError(Exception):
    """Raised when quality gate or linter checks fail."""
    pass


def check_tool_availability() -> dict[str, bool]:
    """Check which CLI linters are available in system PATH."""
    tools = ["terraform", "checkov", "ansible-lint", "git", "docker", "podman"]
    return {tool: shutil.which(tool) is not None for tool in tools}


def run_linter(cmd: list[str], err_msg: str, timeout: int = 30):
    """Execute a single linter command with timeout and error handling."""
    try:
        subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=timeout)
    except FileNotFoundError:
        raise PipelineError(f"Required linter binary '{cmd[0]}' not found in PATH.")
    except subprocess.CalledProcessError as e:
        details = (e.stderr or e.stdout or "").strip()
        raise PipelineError(f"{err_msg}: {details}")
    except subprocess.TimeoutExpired:
        raise PipelineError(f"{err_msg}: Process timed out after {timeout} seconds")


def validate_artifacts(
    build_dir: str, 
    strict: bool = False,
    timeout: int = 30
) -> list[str]:
    """
    Execute syntax and security quality gates across rendered Terraform and Ansible artifacts.
    In strict mode, missing tools will raise PipelineError. In non-strict mode, available
    tools will run and missing tools will be recorded as warnings.
    """
    logs: list[str] = []
    tf_dir = os.path.join(build_dir, "terraform")
    playbook_path = os.path.join(build_dir, "ansible", "playbook_bootstrap.yml")

    # 1. Basic Structural & Syntax Checks
    if not os.path.exists(os.path.join(tf_dir, "main.tf")):
        raise PipelineError("Rendered terraform/main.tf is missing from build directory.")
    if not os.path.exists(playbook_path):
        raise PipelineError("Rendered ansible/playbook_bootstrap.yml is missing from build directory.")

    # 2. Terraform Format Check
    if shutil.which("terraform"):
        run_linter(
            ["terraform", f"-chdir={tf_dir}", "fmt", "-check"],
            "Terraform format validation failed",
            timeout=timeout
        )
        logs.append("Terraform format check passed (terraform fmt -check)")
    else:
        msg = "Terraform CLI not available in PATH; format check skipped"
        if strict:
            raise PipelineError(msg)
        logs.append(f"WARNING: {msg}")

    # 3. Checkov Security Scan
    if shutil.which("checkov"):
        run_linter(
            ["checkov", "-d", tf_dir, "--framework", "terraform", "--compact", "--quiet"],
            "Checkov security scan detected policy violations",
            timeout=timeout
        )
        logs.append("Checkov security scan passed")
    else:
        msg = "Checkov CLI not available in PATH; security scan skipped"
        if strict:
            raise PipelineError(msg)
        logs.append(f"WARNING: {msg}")

    # 4. Ansible-lint Check
    if shutil.which("ansible-lint"):
        run_linter(
            ["ansible-lint", playbook_path],
            "Ansible-lint checks failed",
            timeout=timeout
        )
        logs.append("Ansible-lint check passed")
    else:
        msg = "Ansible-lint CLI not available in PATH; playbook linting skipped"
        if strict:
            raise PipelineError(msg)
        logs.append(f"WARNING: {msg}")

    return logs


def run_containerized_lint(build_dir: str, container_engine: str = "docker", image_name: str = "azure-iac-sandbox:latest") -> list[str]:
    """
    Run the offline linter container against the rendered build directory.
    Mounts build_dir to /workspace inside the sandbox container.
    """
    if not shutil.which(container_engine):
        raise PipelineError(f"Container engine '{container_engine}' is not installed.")

    cmd = [
        container_engine,
        "run",
        "--rm",
        "-v",
        f"{os.path.abspath(build_dir)}:/workspace:ro",
        image_name
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=120)
        return res.stdout.splitlines()
    except subprocess.CalledProcessError as e:
        raise PipelineError(f"Containerized lint scan failed: {e.stderr or e.stdout}")
