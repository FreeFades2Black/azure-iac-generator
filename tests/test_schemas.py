import pytest
from pydantic import ValidationError
from app.models.schemas import (
    InfrastructureBuildRequest,
    RedundancyTier,
    SqlRedundancyTier,
    AZURE_PAIRED_REGIONS,
)

def test_valid_default_zrs_request():
    req = InfrastructureBuildRequest(
        project_name="portalprod",
        github_org_or_user="MyOrg",
        github_repo_name="azure-portal-iac"
    )
    assert req.redundancy == RedundancyTier.ZRS
    assert req.storage_replication_type == "ZRS"
    assert req.primary_region == "eastus"
    assert req.secondary_region is None
    assert req.sql_redundancy == SqlRedundancyTier.ZONE_REDUNDANT


def test_valid_lrs_request():
    req = InfrastructureBuildRequest(
        project_name="devlab01",
        redundancy=RedundancyTier.LRS,
        sql_redundancy=SqlRedundancyTier.LOCAL,
        sql_sku="Basic",
        github_org_or_user="MyOrg",
        github_repo_name="devlab-iac"
    )
    assert req.redundancy == RedundancyTier.LRS
    assert req.storage_replication_type == "LRS"
    assert req.secondary_region is None


def test_valid_gzrs_cross_region_paired():
    req = InfrastructureBuildRequest(
        project_name="missioncrit",
        redundancy=RedundancyTier.GZRS,
        primary_region="eastus",
        primary_vnet_cidr="10.100.0.0/16",
        github_org_or_user="EnterpriseCloud",
        github_repo_name="mission-crit-iac"
    )
    assert req.storage_replication_type == "GZRS"
    assert req.secondary_region == "westus"
    assert req.secondary_vnet_cidr == "10.20.0.0/16"


def test_failover_group_requires_paired_region():
    req = InfrastructureBuildRequest(
        project_name="dataplatform",
        redundancy=RedundancyTier.ZRS,
        primary_region="uksouth",
        sql_redundancy=SqlRedundancyTier.FAILOVER_GROUP,
        sql_sku="GP_Gen5_4",
        github_org_or_user="EnterpriseCloud",
        github_repo_name="sql-fog-iac"
    )
    assert req.secondary_region == "ukwest"


def test_missing_paired_region_fails():
    with pytest.raises(ValidationError) as exc:
        InfrastructureBuildRequest(
            project_name="unpairedtest",
            redundancy=RedundancyTier.GZRS,
            primary_region="australiaeast",  # Not in AZURE_PAIRED_REGIONS
            github_org_or_user="Org",
            github_repo_name="repo"
        )
    assert "lacks an established paired region" in str(exc.value)


def test_cidr_collision_fails():
    with pytest.raises(ValidationError) as exc:
        InfrastructureBuildRequest(
            project_name="cidrtest",
            redundancy=RedundancyTier.GZRS,
            primary_region="eastus",
            primary_vnet_cidr="10.10.0.0/16",
            secondary_vnet_cidr="10.10.0.0/16",  # Overlapping!
            github_org_or_user="Org",
            github_repo_name="repo"
        )
    assert "Primary and Secondary VNet CIDRs must not collide" in str(exc.value)


def test_cidr_overlap_subset_fails():
    with pytest.raises(ValidationError) as exc:
        InfrastructureBuildRequest(
            project_name="overlaptest",
            redundancy=RedundancyTier.GZRS,
            primary_region="eastus",
            primary_vnet_cidr="10.0.0.0/8",
            secondary_vnet_cidr="10.10.0.0/16",  # Subnet of 10.0.0.0/8!
            github_org_or_user="Org",
            github_repo_name="repo"
        )
    assert "Primary and Secondary VNet CIDRs must not collide" in str(exc.value)


def test_disallowed_sql_sku_for_zone_redundancy():
    disallowed_skus = ["Basic", "S0", "S1", "S2"]
    for sku in disallowed_skus:
        with pytest.raises(ValidationError) as exc:
            InfrastructureBuildRequest(
                project_name="sqlsku",
                sql_redundancy=SqlRedundancyTier.ZONE_REDUNDANT,
                sql_sku=sku,
                github_org_or_user="Org",
                github_repo_name="repo"
            )
        assert f"Azure SQL SKU '{sku}' does not support zone redundancy" in str(exc.value)


def test_invalid_project_name_regex():
    # Capital letters not allowed
    with pytest.raises(ValidationError):
        InfrastructureBuildRequest(
            project_name="InvalidName",
            github_org_or_user="Org",
            github_repo_name="repo"
        )

    # Too short (< 3 chars)
    with pytest.raises(ValidationError):
        InfrastructureBuildRequest(
            project_name="ab",
            github_org_or_user="Org",
            github_repo_name="repo"
        )

    # Too long (> 16 chars)
    with pytest.raises(ValidationError):
        InfrastructureBuildRequest(
            project_name="thisprojectnameiswaytoolongtobeaccepted",
            github_org_or_user="Org",
            github_repo_name="repo"
        )


def test_invalid_sql_admin_login():
    # Must start with letter, cannot start with number
    with pytest.raises(ValidationError):
        InfrastructureBuildRequest(
            project_name="adminsql",
            sql_admin_login="123admin",
            github_org_or_user="Org",
            github_repo_name="repo"
        )
