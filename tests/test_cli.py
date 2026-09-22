import json
import os
import shutil
import tempfile
import pytest
from typer.testing import CliRunner
from app.cli import cli

runner = CliRunner()

@pytest.fixture
def temp_output_dir():
    d = tempfile.mkdtemp(prefix="cli_test_")
    yield d
    if os.path.exists(d):
        shutil.rmtree(d, ignore_errors=True)


def test_cli_tools():
    result = runner.invoke(cli, ["tools"])
    assert result.exit_code == 0
    assert "IaC Quality Gate Toolchain" in result.stdout


def test_cli_generate_help():
    result = runner.invoke(cli, ["generate", "--help"])
    assert result.exit_code == 0
    assert "Generate validated Azure Terraform HCL" in result.stdout


def test_cli_generate_execution(temp_output_dir):
    args = [
        "generate",
        "--project-name", "clitest",
        "--redundancy", "zrs",
        "--primary-region", "eastus",
        "--github-user", "CliOrg",
        "--github-repo", "cli-repo",
        "--output-dir", temp_output_dir,
        "--no-validate"
    ]
    result = runner.invoke(cli, args)
    assert result.exit_code == 0
    assert "Artifacts successfully rendered" in result.stdout

    # Verify rendered files
    assert os.path.exists(os.path.join(temp_output_dir, "terraform", "main.tf"))
    assert os.path.exists(os.path.join(temp_output_dir, "ansible", "playbook_bootstrap.yml"))
    assert os.path.exists(os.path.join(temp_output_dir, "ansible", "files", "V1__initial_schema.sql"))


def test_cli_generate_with_config_file(temp_output_dir):
    config_data = {
        "project_name": "cfgtest",
        "redundancy": "lrs",
        "primary_region": "eastus",
        "sql_redundancy": "local",
        "sql_sku": "Basic",
        "github_org_or_user": "ConfigOrg",
        "github_repo_name": "config-repo"
    }
    cfg_file = os.path.join(temp_output_dir, "test_config.json")
    with open(cfg_file, "w") as f:
        json.dump(config_data, f)

    out_dir = os.path.join(temp_output_dir, "rendered")
    args = [
        "generate",
        "--project-name", "dummy",
        "--github-user", "dummy",
        "--github-repo", "dummy",
        "--config", cfg_file,
        "--output-dir", out_dir,
        "--no-validate"
    ]
    result = runner.invoke(cli, args)
    assert result.exit_code == 0
    assert os.path.exists(os.path.join(out_dir, "terraform", "main.tf"))
