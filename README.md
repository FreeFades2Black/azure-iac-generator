# Resilient Azure IaC and Configuration Generator

[![Azure IaC Generator CI](https://github.com/FreeFades2Black/azure-iac-generator/actions/workflows/ci.yml/badge.svg)](https://github.com/FreeFades2Black/azure-iac-generator/actions/workflows/ci.yml)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688?logo=fastapi)](https://fastapi.tiangolo.com)
[![Pydantic v2](https://img.shields.io/badge/Pydantic-v2-E92063?logo=pydantic)](https://docs.pydantic.dev)
[![Terraform](https://img.shields.io/badge/Terraform-1.6+-844FBA?logo=terraform)](https://www.terraform.io)
[![Ansible](https://img.shields.io/badge/Ansible-2.15+-EE0000?logo=ansible)](https://www.ansible.com)
[![Arch Linux / Omarchy](https://img.shields.io/badge/Host-Arch_Linux_Omarchy-1793D1?logo=archlinux)](https://archlinux.org)

An enterprise-grade Python FastAPI service and CLI tool that ingests high-level infrastructure parameters, strictly validates cross-region and resilience constraints, dynamically renders multi-tier Azure Terraform HCL and Ansible bootstrap playbooks, scans artifacts through containerized security and linting quality gates, and publishes versioned repositories directly to GitHub.

---

## Architecture Overview

```
[ User Request / Parameters ]
         │
         ▼
[ Pydantic v2 Contract (app/models/schemas.py) ]
  • Enforces Paired Region Constraints (eastus ◄► westus)
  • Non-Overlapping CIDR Validation (Primary vs Secondary VNet)
  • SQL Tier & Zone Redundancy Compatibility Gate (GP_/BC_ only)
         │
         ▼
[ Jinja2 Rendering Engine (app/engine/generator.py) ]
  ├── Terraform Stack:
  │   ├── LRS (Standalone VM, Standard_LRS) vs ZRS/GZRS (VMSS 3-Zone, StandardSSD_ZRS)
  │   ├── Cross-Region Peering & Secondary RG (GZRS / Failover Group)
  │   └── Azure SQL (Active Directory Admin, Zone Redundant DB, Failover Group)
  └── Ansible Stack:
      ├── IMDS OAuth2 Bearer Token Retrieval
      ├── Baseline DDL Schema Migration (V1__initial_schema.sql)
      └── Entra ID Workload Managed Identity Role Binding
         │
         ▼
[ Quality Gates & Sandbox (app/engine/validator.py) ]
  • Terraform Format Validation (`terraform fmt -check`)
  • Checkov Static Code Security Scanner (Compact/Quiet)
  • Ansible-lint Playbook Validation
  • Containerized Sandbox Runner (`deploy/Dockerfile.sandbox`)
         │
         ▼
[ Git Packaging & GitHub Publisher (app/engine/git_publisher.py) ]
  • Initializes Git branch `main` with sanitized credentials
  • Pushes versioned release to target GitHub repository
```

---

## Target Repository Structure

```
azure-iac-generator/
├── .github/
│   └── workflows/
│       └── ci.yml                 # Automated testing & linting pipeline
├── app/
│   ├── __init__.py
│   ├── main.py                    # FastAPI application entrypoint
│   ├── cli.py                     # Typer / Click CLI interface
│   ├── models/
│   │   ├── __init__.py
│   │   └── schemas.py             # Pydantic v2 validation models
│   ├── engine/
│   │   ├── __init__.py
│   │   ├── generator.py           # Jinja2 template rendering pipeline
│   │   ├── validator.py           # Sandboxed terraform/ansible/checkov gates
│   │   └── git_publisher.py       # Automated Git packaging and GitHub push
│   └── templates/
│       ├── terraform/
│       │   ├── main.tf.j2         # Complete unified multi-tier stack
│       │   ├── versions.tf.j2
│       │   ├── network.tf.j2
│       │   ├── compute.tf.j2
│       │   ├── storage.tf.j2
│       │   ├── sql.tf.j2
│       │   └── outputs.tf.j2
│       └── ansible/
│           ├── hosts.yml.j2
│           ├── playbook_bootstrap.yml.j2
│           ├── templates/
│           │   └── app_user_msi_provision.sql.j2
│           └── files/
│               └── V1__initial_schema.sql
├── deploy/
│   ├── Dockerfile.sandbox         # Rootless offline linter container
│   ├── azure-iac-gen.service      # Systemd unit file for Arch Linux
│   └── omarchy-menu.desktop       # Omarchy application shortcut
├── tests/
│   ├── test_schemas.py            # Model validation & cross-region tests
│   ├── test_generator.py          # Template rendering & HCL checks
│   ├── test_api.py                # FastAPI HTTP endpoint tests
│   └── test_cli.py                # Typer CLI execution tests
├── pyproject.toml
├── requirements.txt
├── .env.example
└── README.md
```

---

## Data Contract & Validation Rules

Defined in [`app/models/schemas.py`](file:///C:/Users/FreeF/projects/azure-iac-generator/app/models/schemas.py):

| Field | Type | Default | Constraints & Business Logic |
| :--- | :--- | :--- | :--- |
| `project_name` | `str` | *Required* | Regex: `^[a-z0-9]{3,16}$` (lowercase alphanumeric only) |
| `redundancy` | `RedundancyTier` | `zrs` | `lrs`, `zrs`, or `gzrs` |
| `primary_region` | `str` | `eastus` | Multi-region requires established pair in `AZURE_PAIRED_REGIONS` |
| `primary_vnet_cidr` | `str` | `10.10.0.0/16` | Valid IPv4 CIDR |
| `secondary_vnet_cidr` | `str` | Auto (`10.20.0.0/16`) | Must **never collide or overlap** with `primary_vnet_cidr` |
| `vm_sku` | `str` | `Standard_D2s_v5` | Sized for production workloads |
| `enable_sql` | `bool` | `True` | Deploy Azure SQL Database |
| `sql_redundancy` | `SqlRedundancyTier` | `zone_redundant` | `local`, `zone_redundant`, or `failover_group` |
| `sql_sku` | `str` | `GP_Gen5_2` | Zone redundancy **disallows** `Basic`, `S0`, `S1`, `S2`. Must use `GP_` or `BC_`. |
| `sql_admin_login` | `str` | `sqladminuser` | Regex: `^[a-zA-Z][a-zA-Z0-9_]{4,15}$` |
| `app_msi_display_name` | `str` | `id-app-workload-prod` | Entra ID Managed Identity assigned inside SQL |
| `github_org_or_user` | `str` | *Required* | Target GitHub account / org |
| `github_repo_name` | `str` | *Required* | Regex: `^[a-zA-Z0-9_\.-]+$` |

---

## Local Quickstart & Development

### 1. Prerequisites
- Python 3.10+ (Tested on 3.11 & 3.12)
- Git 2.40+

### 2. Setup Virtual Environment
```bash
cd azure-iac-generator
python -m venv .venv

# On Linux / Arch Omarchy:
source .venv/bin/activate

# On Windows:
.venv\Scripts\Activate.ps1

pip install -r requirements.txt
```

### 3. Run the CLI
```bash
# Verify local toolchain
python -m app.cli tools

# Render ZRS multi-tier stack locally
python -m app.cli generate \
  --project-name "portalprod" \
  --redundancy "zrs" \
  --primary-region "eastus" \
  --github-user "FreeFades2Black" \
  --github-repo "azure-portal-prod" \
  --output-dir "./dist/portalprod"
```

### 4. Run the FastAPI Web Service
```bash
# Start server with live reload
python -m app.cli serve --host 127.0.0.1 --port 8080 --reload

# Or via Uvicorn directly
uvicorn app.main:app --host 127.0.0.1 --port 8080 --reload
```
Interactive Swagger API documentation is available at: **http://127.0.0.1:8080/docs**

---

## REST API Specification

### `GET /health`
Returns system status and availability of local CLI linters.
```json
{
  "status": "ok",
  "service": "azure-iac-generator",
  "version": "1.0.0",
  "tools_available": {
    "terraform": true,
    "checkov": true,
    "ansible-lint": true,
    "git": true,
    "docker": true,
    "podman": false
  }
}
```

### `POST /api/v1/generate`
Generates Terraform and Ansible artifacts into a sandboxed build directory.
```bash
curl -X POST http://127.0.0.1:8080/api/v1/generate \
  -H "Content-Type: application/json" \
  -d '{
    "project_name": "crmprod",
    "redundancy": "gzrs",
    "primary_region": "eastus",
    "primary_vnet_cidr": "10.10.0.0/16",
    "secondary_vnet_cidr": "10.20.0.0/16",
    "enable_sql": true,
    "sql_redundancy": "failover_group",
    "sql_sku": "GP_Gen5_4",
    "github_org_or_user": "FreeFades2Black",
    "github_repo_name": "azure-crm-iac"
  }'
```

### `POST /api/v1/validate`
Performs a dry-run generation and linter scan without creating permanent files on disk.

### `POST /api/v1/publish`
Renders, validates, and pushes the generated repository directly to GitHub using your personal access token (via `X-GitHub-Token` header or `GITHUB_TOKEN` environment variable).

---

## Containerized Offline Sandbox Linter

To guarantee deterministic, zero-dependency validation regardless of what is installed on the host:

```bash
# Build sandbox image
docker build -t azure-iac-sandbox:latest -f deploy/Dockerfile.sandbox .

# Execute offline security and syntax audit against any generated directory
docker run --rm -v $(pwd)/dist/portalprod:/workspace:ro azure-iac-sandbox:latest
```

The container runs unprivileged as non-root user `sandbox` and executes:
1. `terraform -chdir=terraform fmt -check`
2. `checkov -d terraform --framework terraform --compact --quiet`
3. `ansible-lint ansible/playbook_bootstrap.yml`

---

## Bare-Metal Omarchy / Arch Linux Host Deployment

To run the generator as a persistent local systemd daemon on your Arch Linux Omarchy desktop:

```bash
# 1. Setup project on Arch host
cd ~/projects/azure-iac-generator
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 2. Install native linters via Arch pacman
sudo pacman -S --needed terraform checkov ansible-lint git

# 3. Install systemd service unit
sudo cp deploy/azure-iac-gen.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now azure-iac-gen.service

# 4. Install Omarchy desktop shortcut
cp deploy/omarchy-menu.desktop ~/.local/share/applications/
update-desktop-database ~/.local/share/applications/

# 5. Verify service health
curl -s http://127.0.0.1:8080/health | jq .
```

---

## Running the Automated Test Suite

```bash
pytest -v
```
All unit tests, cross-region constraint validations, template rendering assertions, and FastAPI endpoint routes run in under 3 seconds.
