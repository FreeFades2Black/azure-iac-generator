from enum import Enum
import ipaddress
from pydantic import BaseModel, Field, model_validator

class RedundancyTier(str, Enum):
    LRS = "lrs"
    ZRS = "zrs"
    GZRS = "gzrs"

class SqlRedundancyTier(str, Enum):
    LOCAL = "local"
    ZONE_REDUNDANT = "zone_redundant"
    FAILOVER_GROUP = "failover_group"

AZURE_PAIRED_REGIONS = {
    "eastus": "westus",
    "eastus2": "centralus",
    "northeurope": "westeurope",
    "uksouth": "ukwest"
}

class InfrastructureBuildRequest(BaseModel):
    project_name: str = Field(..., pattern=r"^[a-z0-9]{3,16}$", description="Lowercase alphanumeric only")
    redundancy: RedundancyTier = Field(default=RedundancyTier.ZRS)
    primary_region: str = Field(default="eastus")
    primary_vnet_cidr: str = Field(default="10.10.0.0/16")
    secondary_vnet_cidr: str | None = Field(default=None)
    vm_sku: str = Field(default="Standard_D2s_v5")
    packages: list[str] = Field(default_factory=lambda: ["curl", "git", "nginx", "jq"])

    # Azure SQL Database Configuration
    enable_sql: bool = Field(default=True)
    sql_redundancy: SqlRedundancyTier = Field(default=SqlRedundancyTier.ZONE_REDUNDANT)
    sql_sku: str = Field(default="GP_Gen5_2")
    sql_admin_login: str = Field(default="sqladminuser", pattern=r"^[a-zA-Z][a-zA-Z0-9_]{4,15}$")
    app_msi_display_name: str = Field(default="id-app-workload-prod")

    # GitHub Publishing Target
    github_org_or_user: str = Field(..., description="Target GitHub user/org name")
    github_repo_name: str = Field(..., pattern=r"^[a-zA-Z0-9_\.-]+$")

    @model_validator(mode="after")
    def validate_cross_region_constraints(self):
        requires_multi_region = (
            self.redundancy == RedundancyTier.GZRS or 
            self.sql_redundancy == SqlRedundancyTier.FAILOVER_GROUP
        )

        if requires_multi_region:
            if self.primary_region not in AZURE_PAIRED_REGIONS:
                raise ValueError(
                    f"Primary region '{self.primary_region}' lacks an established paired region. "
                    f"Allowed: {list(AZURE_PAIRED_REGIONS.keys())}"
                )
            
            if not self.secondary_vnet_cidr:
                self.secondary_vnet_cidr = "10.20.0.0/16"
            
            p_net = ipaddress.ip_network(self.primary_vnet_cidr)
            s_net = ipaddress.ip_network(self.secondary_vnet_cidr)
            if p_net.overlaps(s_net):
                raise ValueError("Primary and Secondary VNet CIDRs must not collide.")

        if self.sql_redundancy in (SqlRedundancyTier.ZONE_REDUNDANT, SqlRedundancyTier.FAILOVER_GROUP):
            disallowed = ["Basic", "S0", "S1", "S2"]
            if any(self.sql_sku.startswith(prefix) for prefix in disallowed):
                raise ValueError(f"Azure SQL SKU '{self.sql_sku}' does not support zone redundancy. Use GP_ or BC_.")

        return self

    @property
    def secondary_region(self) -> str | None:
        if self.redundancy == RedundancyTier.GZRS or self.sql_redundancy == SqlRedundancyTier.FAILOVER_GROUP:
            return AZURE_PAIRED_REGIONS[self.primary_region]
        return None

    @property
    def storage_replication_type(self) -> str:
        return {
            RedundancyTier.LRS: "LRS",
            RedundancyTier.ZRS: "ZRS",
            RedundancyTier.GZRS: "GZRS"
        }[self.redundancy]


class BuildResponse(BaseModel):
    status: str = "success"
    message: str
    project_name: str
    redundancy: RedundancyTier
    primary_region: str
    secondary_region: str | None = None
    output_dir: str
    manifest: list[str] = Field(default_factory=list)
    validation_passed: bool = True
    validation_details: list[str] = Field(default_factory=list)
    compliance_scan: dict | None = None



class PublishResponse(BaseModel):
    status: str = "success"
    message: str
    github_repo_url: str
    branch: str = "main"
    commit_message: str


class HealthResponse(BaseModel):
    status: str = "ok"
    service: str = "azure-iac-generator"
    version: str = "1.0.0"
    tools_available: dict[str, bool] = Field(default_factory=dict)
