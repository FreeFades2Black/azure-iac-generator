import os
import shutil
import pytest
from app.models.schemas import (
    InfrastructureBuildRequest,
    RedundancyTier,
    SqlRedundancyTier,
)
from app.engine.generator import render_and_validate

@pytest.fixture
def clean_build_dirs():
    dirs = []
    yield dirs
    for d in dirs:
        if os.path.exists(d):
            shutil.rmtree(d, ignore_errors=True)


def test_render_lrs_standalone_vm(clean_build_dirs):
    req = InfrastructureBuildRequest(
        project_name="testlrs",
        redundancy=RedundancyTier.LRS,
        sql_redundancy=SqlRedundancyTier.LOCAL,
        sql_sku="Basic",
        github_org_or_user="TestOrg",
        github_repo_name="test-repo"
    )
    build_dir = render_and_validate(req, run_validation=False)
    clean_build_dirs.append(build_dir)

    tf_main = os.path.join(build_dir, "terraform", "main.tf")
    assert os.path.exists(tf_main)
    with open(tf_main, "r", encoding="utf-8") as f:
        content = f.read()

    # Must contain standalone VM, not scale set
    assert "azurerm_linux_virtual_machine" in content
    assert "azurerm_linux_virtual_machine_scale_set" not in content
    assert 'account_replication_type  = "LRS"' in content
    assert "Standard_LRS" in content
    assert "rg-testlrs-eastus" in content

    # Check Ansible files
    playbook_file = os.path.join(build_dir, "ansible", "playbook_bootstrap.yml")
    assert os.path.exists(playbook_file)
    schema_file = os.path.join(build_dir, "ansible", "files", "V1__initial_schema.sql")
    assert os.path.exists(schema_file)


def test_render_zrs_vmss(clean_build_dirs):
    req = InfrastructureBuildRequest(
        project_name="testzrs",
        redundancy=RedundancyTier.ZRS,
        github_org_or_user="TestOrg",
        github_repo_name="test-repo"
    )
    build_dir = render_and_validate(req, run_validation=False)
    clean_build_dirs.append(build_dir)

    tf_main = os.path.join(build_dir, "terraform", "main.tf")
    with open(tf_main, "r", encoding="utf-8") as f:
        content = f.read()

    # Must contain VMSS with multi-zone distribution
    assert "azurerm_linux_virtual_machine_scale_set" in content
    assert 'zones               = ["1", "2", "3"]' in content
    assert "StandardSSD_ZRS" in content
    assert 'account_replication_type  = "ZRS"' in content
    assert "zone_redundant = true" in content


def test_render_gzrs_paired_region_and_peering(clean_build_dirs):
    req = InfrastructureBuildRequest(
        project_name="testgzrs",
        redundancy=RedundancyTier.GZRS,
        primary_region="eastus",
        github_org_or_user="TestOrg",
        github_repo_name="test-repo"
    )
    build_dir = render_and_validate(req, run_validation=False)
    clean_build_dirs.append(build_dir)

    tf_main = os.path.join(build_dir, "terraform", "main.tf")
    with open(tf_main, "r", encoding="utf-8") as f:
        content = f.read()

    # Secondary region is westus
    assert "rg-testgzrs-westus" in content
    assert "vnet-testgzrs-westus" in content
    assert "azurerm_virtual_network_peering" in content
    assert "peer_primary_to_secondary" in content
    assert "peer_secondary_to_primary" in content
    assert 'account_replication_type  = "GZRS"' in content


def test_render_sql_failover_group(clean_build_dirs):
    req = InfrastructureBuildRequest(
        project_name="testfog",
        redundancy=RedundancyTier.ZRS,
        primary_region="eastus2",
        sql_redundancy=SqlRedundancyTier.FAILOVER_GROUP,
        sql_sku="GP_Gen5_4",
        github_org_or_user="TestOrg",
        github_repo_name="test-repo"
    )
    build_dir = render_and_validate(req, run_validation=False)
    clean_build_dirs.append(build_dir)

    tf_main = os.path.join(build_dir, "terraform", "main.tf")
    with open(tf_main, "r", encoding="utf-8") as f:
        content = f.read()

    # Secondary region is centralus
    assert "azurerm_mssql_failover_group" in content
    assert "fog-testfog" in content
    assert "sql-testfog-sec" in content
    assert "${azurerm_mssql_failover_group.sql_fog.name}.database.windows.net" in content


def test_ansible_bootstrap_playbook_contents(clean_build_dirs):
    req = InfrastructureBuildRequest(
        project_name="testans",
        app_msi_display_name="id-app-custom-prod",
        github_org_or_user="TestOrg",
        github_repo_name="test-repo"
    )
    build_dir = render_and_validate(req, run_validation=False)
    clean_build_dirs.append(build_dir)

    playbook_path = os.path.join(build_dir, "ansible", "playbook_bootstrap.yml")
    with open(playbook_path, "r", encoding="utf-8") as f:
        content = f.read()

    assert "id-app-custom-prod" in content
    assert "169.254.169.254" in content
    assert "sql-testans-prim.database.windows.net" in content
    assert "ActiveDirectoryAccessToken" in content
    assert "schema_version" in content
