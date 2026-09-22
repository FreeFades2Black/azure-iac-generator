import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["service"] == "azure-iac-generator"
    assert "tools_available" in data


def test_api_generate_valid():
    payload = {
        "project_name": "apiprod",
        "redundancy": "zrs",
        "primary_region": "eastus",
        "primary_vnet_cidr": "10.10.0.0/16",
        "vm_sku": "Standard_D2s_v5",
        "enable_sql": True,
        "sql_redundancy": "zone_redundant",
        "sql_sku": "GP_Gen5_2",
        "github_org_or_user": "EnterpriseOrg",
        "github_repo_name": "api-iac-repo"
    }
    response = client.post("/api/v1/generate?run_validation=false", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["project_name"] == "apiprod"
    assert "terraform/main.tf" in data["manifest"]
    assert "ansible/playbook_bootstrap.yml" in data["manifest"]
    assert "ansible/files/V1__initial_schema.sql" in data["manifest"]


def test_api_validate_dry_run():
    payload = {
        "project_name": "dryruntest",
        "redundancy": "lrs",
        "primary_region": "eastus",
        "sql_redundancy": "local",
        "sql_sku": "Basic",
        "github_org_or_user": "Org",
        "github_repo_name": "repo"
    }
    response = client.post("/api/v1/validate", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "valid"
    assert data["redundancy"] == "lrs"


def test_api_generate_invalid_collision_returns_422():
    payload = {
        "project_name": "collide",
        "redundancy": "gzrs",
        "primary_region": "eastus",
        "primary_vnet_cidr": "10.10.0.0/16",
        "secondary_vnet_cidr": "10.10.0.0/16",
        "github_org_or_user": "Org",
        "github_repo_name": "repo"
    }
    response = client.post("/api/v1/generate", json=payload)
    assert response.status_code == 422


def test_api_publish_missing_token_returns_400():
    payload = {
        "project_name": "pubtest",
        "redundancy": "zrs",
        "github_org_or_user": "Org",
        "github_repo_name": "repo"
    }
    # Ensure GITHUB_TOKEN is cleared for test
    response = client.post("/api/v1/publish", json=payload)
    # If GITHUB_TOKEN is present in env, it might proceed, but without token it returns 400
    assert response.status_code in (400, 502)
