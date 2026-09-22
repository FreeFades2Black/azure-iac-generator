import os
import shutil
import tempfile
from pathlib import Path
from jinja2 import Environment, FileSystemLoader

from app.models.schemas import InfrastructureBuildRequest
from app.engine.validator import PipelineError, validate_artifacts, run_linter

def get_templates_dir() -> Path:
    """Resolve the absolute path to app/templates directory."""
    pkg_dir = Path(__file__).resolve().parent.parent / "templates"
    if pkg_dir.exists():
        return pkg_dir
    local_dir = Path("app/templates").resolve()
    if local_dir.exists():
        return local_dir
    raise FileNotFoundError(f"Template directory not found at {pkg_dir} or {local_dir}")


def build_template_context(request: InfrastructureBuildRequest) -> dict:
    """Construct full template context including computed properties."""
    context = request.model_dump()
    context["secondary_region"] = request.secondary_region
    context["storage_replication_type"] = request.storage_replication_type
    context["redundancy_value"] = request.redundancy.value
    context["sql_redundancy_value"] = request.sql_redundancy.value
    return context


def render_and_validate(
    request: InfrastructureBuildRequest,
    target_dir: str | None = None,
    run_validation: bool = True,
    strict_validation: bool = False
) -> str:
    """
    Renders multi-tier Azure Terraform and Ansible templates into an isolated build folder,
    copies migration scripts, and optionally enforces syntax/security quality gates.
    Returns the path to the generated build directory.
    """
    # 1. Directory Structure Initialization
    if target_dir:
        temp_dir = target_dir
        os.makedirs(temp_dir, exist_ok=True)
    else:
        temp_dir = tempfile.mkdtemp(prefix=f"iac_build_{request.project_name}_")

    tf_dir = os.path.join(temp_dir, "terraform")
    ansible_dir = os.path.join(temp_dir, "ansible")
    ansible_files_dir = os.path.join(ansible_dir, "files")
    ansible_templates_dir = os.path.join(ansible_dir, "templates")

    os.makedirs(tf_dir, exist_ok=True)
    os.makedirs(ansible_files_dir, exist_ok=True)
    os.makedirs(ansible_templates_dir, exist_ok=True)

    templates_path = get_templates_dir()
    env = Environment(
        loader=FileSystemLoader(str(templates_path)),
        trim_blocks=True,
        lstrip_blocks=True,
        autoescape=False
    )
    context = build_template_context(request)

    # 2. Render Main Terraform Stack
    tf_template = env.get_template("terraform/main.tf.j2")
    with open(os.path.join(tf_dir, "main.tf"), "w", encoding="utf-8") as f:
        f.write(tf_template.render(context))

    # Also render modular split files for enterprise flexibility
    modular_templates = [
        ("terraform/versions.tf.j2", "versions.tf"),
        ("terraform/network.tf.j2", "network.tf"),
        ("terraform/compute.tf.j2", "compute.tf"),
        ("terraform/storage.tf.j2", "storage.tf"),
        ("terraform/sql.tf.j2", "sql.tf"),
        ("terraform/outputs.tf.j2", "outputs.tf"),
    ]
    modules_dir = os.path.join(tf_dir, "modules")
    os.makedirs(modules_dir, exist_ok=True)
    for tmpl_rel, out_name in modular_templates:
        try:
            tmpl = env.get_template(tmpl_rel)
            with open(os.path.join(modules_dir, out_name), "w", encoding="utf-8") as f:
                f.write(tmpl.render(context))
        except Exception:
            pass

    # 3. Render Ansible Playbook & Inventory
    ans_template = env.get_template("ansible/playbook_bootstrap.yml.j2")
    with open(os.path.join(ansible_dir, "playbook_bootstrap.yml"), "w", encoding="utf-8") as f:
        f.write(ans_template.render(context))

    hosts_template = env.get_template("ansible/hosts.yml.j2")
    with open(os.path.join(ansible_dir, "hosts.yml"), "w", encoding="utf-8") as f:
        f.write(hosts_template.render(context))

    msi_template = env.get_template("ansible/templates/app_user_msi_provision.sql.j2")
    with open(os.path.join(ansible_templates_dir, "app_user_msi_provision.sql"), "w", encoding="utf-8") as f:
        f.write(msi_template.render(context))

    # 4. Copy Static Baseline DDL Migration
    src_v1 = templates_path / "ansible" / "files" / "V1__initial_schema.sql"
    if src_v1.exists():
        shutil.copy(str(src_v1), os.path.join(ansible_files_dir, "V1__initial_schema.sql"))
    else:
        # Fallback inline generation if file not found
        with open(os.path.join(ansible_files_dir, "V1__initial_schema.sql"), "w", encoding="utf-8") as f:
            f.write("-- V1__initial_schema.sql fallback\nCREATE TABLE dbo.schema_version (version INT PRIMARY KEY);\n")

    # 5. Generate Target Git Repository Readme & Gitignore
    with open(os.path.join(temp_dir, ".gitignore"), "w", encoding="utf-8") as f:
        f.write(".terraform/\n*.tfstate\n*.tfstate.*\n*.retry\n*.log\n.env\n")

    with open(os.path.join(temp_dir, "README.md"), "w", encoding="utf-8") as f:
        f.write(
            f"# {request.project_name.upper()} - Azure Resilient Infrastructure\n\n"
            f"- **Primary Region:** `{request.primary_region}`\n"
            f"- **Secondary Region:** `{request.secondary_region or 'N/A'}`\n"
            f"- **Storage Redundancy:** `{request.storage_replication_type}`\n"
            f"- **Compute Tier:** `{request.vm_sku}`\n"
            f"- **Azure SQL:** `{'Enabled' if request.enable_sql else 'Disabled'}` "
            f"(`{request.sql_sku}`, Redundancy: `{request.sql_redundancy.value}`)\n\n"
            f"Generated automatically by Antigravity Azure IaC & Configuration Generator.\n"
        )

    # 6. Quality & Security Validation Gates
    if run_validation:
        validate_artifacts(temp_dir, strict=strict_validation)

    return temp_dir


def _run_linter(cmd: list[str], err_msg: str):
    """Backwards-compatible linter execution helper."""
    run_linter(cmd, err_msg)
