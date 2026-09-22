import json
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from app.engine.validator import SecurityValidator, ComplianceViolationError
from app.main import app

client = TestClient(app)

def test_security_validator_skipped_when_unavailable():
    validator = SecurityValidator()
    validator.checkov_bin = None  # simulate missing binary
    assert not validator.is_available
    result = validator.scan_terraform_directory("/tmp/fake_dir")
    assert result["status"] == "skipped"
    assert "not found in PATH" in result["reason"]


def test_compliance_violation_error_raised():
    validator = SecurityValidator()
    validator.checkov_bin = "/usr/bin/checkov"

    mock_checkov_output = {
        "results": {
            "failed_checks": [
                {
                    "check_id": "CKV_AZURE_3",
                    "check_name": "Ensure storage account is using the latest TLS version",
                    "severity": "HIGH",
                    "resource": "azurerm_storage_account.storage",
                    "guideline": "https://docs.prismacloud.io/en/enterprise-edition/policy-reference/azure-policies/azure-general-policies/ensure-storage-account-is-using-the-latest-version-of-tls",
                    "file_path": "/terraform/main.tf"
                }
            ],
            "passed_checks": []
        }
    }

    mock_proc = MagicMock()
    mock_proc.returncode = 1
    mock_proc.stdout = json.dumps(mock_checkov_output)
    mock_proc.stderr = ""

    with patch("subprocess.run", return_value=mock_proc):
        with pytest.raises(ComplianceViolationError) as exc_info:
            validator.scan_terraform_directory("/tmp/fake_dir")

        err = exc_info.value
        assert "1 blocking CIS Azure / High-severity violations" in str(err)
        assert len(err.violations) == 1
        assert err.violations[0]["check_id"] == "CKV_AZURE_3"
        assert err.violations[0]["severity"] == "HIGH"
        assert err.violations[0]["resource"] == "azurerm_storage_account.storage"


def test_api_returns_422_on_compliance_violation():
    mock_violations = [
        {
            "check_id": "CKV_AZURE_3",
            "check_name": "Ensure storage account is using the latest TLS version",
            "severity": "HIGH",
            "resource": "azurerm_storage_account.storage",
            "guideline": "https://docs.prismacloud.io/guidelines/ckv_azure_3",
            "file_path": "/terraform/main.tf"
        }
    ]

    with patch.object(
        SecurityValidator,
        "scan_terraform_directory",
        side_effect=ComplianceViolationError("Checkov compliance scan failed with 1 blocking CIS Azure / High-severity violations.", mock_violations)
    ):
        with patch.object(SecurityValidator, "is_available", True):
            payload = {
                "project_name": "violatetest",
                "redundancy": "zrs",
                "primary_region": "eastus",
                "github_org_or_user": "TestOrg",
                "github_repo_name": "violate-repo"
            }
            response = client.post("/api/v1/generate", json=payload)
            assert response.status_code == 422
            data = response.json()
            assert data["status"] == "failed_compliance_gate"
            assert "1 blocking CIS Azure" in data["error"]
            assert len(data["violations"]) == 1
            assert data["violations"][0]["check_id"] == "CKV_AZURE_3"


def test_security_validator_passed_scan():
    validator = SecurityValidator()
    validator.checkov_bin = "/usr/bin/checkov"

    mock_checkov_output = {
        "results": {
            "failed_checks": [],
            "passed_checks": [
                {"check_id": "CKV_AZURE_1"},
                {"check_id": "CKV_AZURE_3"},
                {"check_id": "CKV_AZURE_18"}
            ]
        }
    }

    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.stdout = json.dumps(mock_checkov_output)
    mock_proc.stderr = ""

    with patch("subprocess.run", return_value=mock_proc):
        result = validator.scan_terraform_directory("/tmp/fake_dir")
        assert result["status"] == "passed"
        assert result["checks_passed"] == 3
        assert result["violations_detected"] == 0
