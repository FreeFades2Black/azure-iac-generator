import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

class PipelineError(Exception):
    """Raised when quality gate or linter checks fail."""
    pass


class ComplianceViolationError(Exception):
    """Raised when Checkov detects blocking CIS benchmark or high/critical policy violations."""
    def __init__(self, message: str, violations: list[dict[str, Any]]):
        super().__init__(message)
        self.violations = violations


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


class SecurityValidator:
    """
    Dedicated Checkov policy enforcement gate for CIS Azure Foundations Benchmark
    and high/critical severity infrastructure compliance.
    """
    def __init__(self, config_path: str | Path | None = None):
        if config_path:
            self.config_path = str(config_path)
        else:
            pkg_config = Path(__file__).resolve().parent / "checkov_config.yaml"
            if pkg_config.exists():
                self.config_path = str(pkg_config)
            else:
                self.config_path = "app/engine/checkov_config.yaml"
        self.checkov_bin = shutil.which("checkov")

    @property
    def is_available(self) -> bool:
        return self.checkov_bin is not None

    def scan_terraform_directory(self, target_dir: str | Path) -> dict[str, Any]:
        """
        Executes Checkov against a rendered Terraform directory.
        Raises ComplianceViolationError if any high/critical checks fail.
        """
        if not self.is_available:
            return {
                "status": "skipped",
                "reason": "Checkov binary not found in PATH"
            }

        cmd = [
            self.checkov_bin,
            "-d", str(target_dir),
            "--config-file", self.config_path,
            "--output", "json"
        ]

        # Checkov exit codes:
        # 0: all passed
        # 1: failures found based on hard-fail thresholds
        # 2: execution syntax error or bad parameters
        process = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60
        )

        try:
            scan_data = json.loads(process.stdout) if process.stdout.strip() else {}
        except json.JSONDecodeError:
            if process.returncode != 0:
                raise RuntimeError(f"Checkov process execution error: {process.stderr}")
            scan_data = {}

        # Parse results (Checkov returns a dict for single framework or list for multiple)
        if isinstance(scan_data, list):
            results = scan_data[0].get("results", {}) if scan_data else {}
        else:
            results = scan_data.get("results", {})

        failed_checks = results.get("failed_checks", [])

        # Filter for blocking CIS / High / Critical rules
        blocking_violations = []
        for check in failed_checks:
            severity = check.get("severity", "UNKNOWN")
            check_id = check.get("check_id")
            check_name = check.get("check_name")
            resource = check.get("resource")
            guideline = check.get("guideline")

            blocking_violations.append({
                "check_id": check_id,
                "check_name": check_name,
                "severity": severity,
                "resource": resource,
                "guideline": guideline,
                "file_path": check.get("file_path")
            })

        if blocking_violations:
            summary_msg = (
                f"Checkov compliance scan failed with {len(blocking_violations)} "
                f"blocking CIS Azure / High-severity violations."
            )
            raise ComplianceViolationError(summary_msg, blocking_violations)

        passed_count = len(results.get("passed_checks", []))
        return {
            "status": "passed",
            "checks_passed": passed_count,
            "violations_detected": 0
        }


def validate_artifacts(
    build_dir: str, 
    strict: bool = False,
    timeout: int = 30
) -> list[str]:
    """
    Execute syntax and security quality gates across rendered Terraform and Ansible artifacts.
    Runs terraform fmt, SecurityValidator Checkov scan, and ansible-lint.
    """
    logs: list[str] = []
    tf_dir = os.path.join(build_dir, "terraform")
    playbook_path = os.path.join(build_dir, "ansible", "playbook_bootstrap.yml")

    # 1. Structural Checks
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

    # 3. Checkov Policy Gate
    sec_validator = SecurityValidator()
    if sec_validator.is_available:
        scan_result = sec_validator.scan_terraform_directory(tf_dir)
        passed = scan_result.get("checks_passed", 0)
        logs.append(f"Checkov compliance scan passed ({passed} checks verified)")
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
    """Run offline linter container against the rendered build directory."""
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
