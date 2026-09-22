import json
import os
from pathlib import Path
from typing import Optional
import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from app.models.schemas import (
    InfrastructureBuildRequest,
    RedundancyTier,
    SqlRedundancyTier,
)
from app.engine.generator import render_and_validate
from app.engine.validator import check_tool_availability, validate_artifacts
from app.engine.git_publisher import push_to_github

cli = typer.Typer(
    name="azure-iac-gen",
    help="Resilient Azure IaC and Configuration Generator CLI",
    add_completion=False
)
console = Console()


@cli.command("tools")
def show_tools():
    """Display availability status of local quality gate tools."""
    tools = check_tool_availability()
    table = Table(title="IaC Quality Gate Toolchain", show_header=True, header_style="bold cyan")
    table.add_column("Tool", style="dim")
    table.add_column("Status")
    table.add_column("Purpose")

    descriptions = {
        "terraform": "HashiCorp Terraform CLI (fmt & validate)",
        "checkov": "Bridgecrew Checkov Static Code Security Scanner",
        "ansible-lint": "Ansible Best Practices & Syntax Linter",
        "git": "Version Control & Automated Release Publisher",
        "docker": "Container Engine for Sandbox Execution",
        "podman": "Rootless Container Engine for Sandbox Execution"
    }

    for tool, available in tools.items():
        status = "[bold green]ONLINE[/bold green]" if available else "[yellow]NOT INSTALLED[/yellow]"
        table.add_row(tool, status, descriptions.get(tool, ""))

    console.print(table)


@cli.command("generate")
def generate(
    project_name: str = typer.Option(..., "--project-name", "-p", help="3-16 lowercase alphanumeric chars"),
    redundancy: RedundancyTier = typer.Option(RedundancyTier.ZRS, "--redundancy", "-r", help="lrs, zrs, or gzrs"),
    primary_region: str = typer.Option("eastus", "--primary-region", help="Primary Azure region"),
    primary_vnet_cidr: str = typer.Option("10.10.0.0/16", "--primary-vnet-cidr", "--primary-vnet", help="Primary VNet CIDR"),
    secondary_vnet_cidr: Optional[str] = typer.Option(None, "--secondary-vnet-cidr", "--secondary-vnet", help="Secondary VNet CIDR (for GZRS/Failover)"),
    vm_sku: str = typer.Option("Standard_D2s_v5", "--vm-sku", help="Virtual machine / VMSS SKU"),
    enable_sql: bool = typer.Option(True, "--enable-sql/--no-sql", help="Deploy Azure SQL Database"),
    sql_redundancy: SqlRedundancyTier = typer.Option(SqlRedundancyTier.ZONE_REDUNDANT, "--sql-redundancy", help="local, zone_redundant, failover_group"),
    sql_sku: str = typer.Option("GP_Gen5_2", "--sql-sku", help="Azure SQL Database SKU (GP_ or BC_ for zone redundancy)"),
    sql_admin_login: str = typer.Option("sqladminuser", "--sql-admin", help="SQL Admin login username"),
    app_msi_display_name: str = typer.Option("id-app-workload-prod", "--msi-name", help="Entra ID Managed Identity display name"),
    github_org_or_user: str = typer.Option(..., "--github-user", "--github-org-or-user", "-u", help="GitHub username or organization"),
    github_repo_name: str = typer.Option(..., "--github-repo", "--github-repo-name", help="Target GitHub repository name"),
    output_dir: Optional[str] = typer.Option(None, "--output-dir", "-o", help="Target output folder"),
    config_file: Optional[Path] = typer.Option(None, "--config", "-c", help="Load parameters from JSON config file"),
    validate: bool = typer.Option(True, "--validate/--no-validate", help="Run local linter checks"),
    strict: bool = typer.Option(False, "--strict", help="Require all linters to be installed in PATH")
):
    """
    Generate validated Azure Terraform HCL and Ansible bootstrap playbooks.
    """
    try:
        if config_file:
            with open(config_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            request = InfrastructureBuildRequest(**data)
        else:
            request = InfrastructureBuildRequest(
                project_name=project_name,
                redundancy=redundancy,
                primary_region=primary_region,
                primary_vnet_cidr=primary_vnet_cidr,
                secondary_vnet_cidr=secondary_vnet_cidr,
                vm_sku=vm_sku,
                enable_sql=enable_sql,
                sql_redundancy=sql_redundancy,
                sql_sku=sql_sku,
                sql_admin_login=sql_admin_login,
                app_msi_display_name=app_msi_display_name,
                github_org_or_user=github_org_or_user,
                github_repo_name=github_repo_name
            )

        console.print(Panel.fit(
            f"[bold cyan]Rendering Infrastructure Stack[/bold cyan]\n"
            f"Project: [green]{request.project_name}[/green]\n"
            f"Redundancy: [yellow]{request.redundancy.value.upper()}[/yellow] (Storage: {request.storage_replication_type})\n"
            f"Primary Region: [blue]{request.primary_region}[/blue] | Secondary: [magenta]{request.secondary_region or 'None'}[/magenta]\n"
            f"Azure SQL: [cyan]{request.sql_sku}[/cyan] ({request.sql_redundancy.value})",
            title="Azure IaC Generator"
        ))

        build_path = render_and_validate(
            request=request,
            target_dir=output_dir,
            run_validation=validate,
            strict_validation=strict
        )

        console.print(f"\n[bold green][SUCCESS] Artifacts successfully rendered at:[/bold green] {build_path}\n")

        # Display file tree
        table = Table(title="Generated Artifact Manifest", show_header=True)
        table.add_column("Relative Path", style="cyan")
        table.add_column("Size (Bytes)", justify="right")

        for root, _, files in os.walk(build_path):
            for file in sorted(files):
                full_p = os.path.join(root, file)
                rel_p = os.path.relpath(full_p, build_path).replace("\\", "/")
                table.add_row(rel_p, str(os.path.getsize(full_p)))

        console.print(table)

    except Exception as e:
        console.print(f"[bold red]Generation Failed:[/bold red] {e}")
        raise typer.Exit(code=1)


@cli.command("publish")
def publish(
    config_file: Path = typer.Option(..., "--config", "-c", help="Path to JSON configuration file"),
    token: Optional[str] = typer.Option(None, "--token", "-t", help="GitHub Personal Access Token (defaults to GITHUB_TOKEN env)"),
    validate: bool = typer.Option(True, "--validate/--no-validate")
):
    """
    Render, validate, and push directly to designated GitHub repository.
    """
    try:
        with open(config_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        request = InfrastructureBuildRequest(**data)

        console.print(f"[cyan]Rendering and validating {request.project_name}...[/cyan]")
        build_path = render_and_validate(request, run_validation=validate)

        console.print(f"[cyan]Publishing to https://github.com/{request.github_org_or_user}/{request.github_repo_name}...[/cyan]")
        repo_url = push_to_github(build_path, request, token=token)

        console.print(f"[bold green][SUCCESS] Successfully published release to:[/bold green] {repo_url}")
    except Exception as e:
        console.print(f"[bold red]Publish Failed:[/bold red] {e}")
        raise typer.Exit(code=1)


@cli.command("serve")
def serve(
    host: str = typer.Option("127.0.0.1", "--host", "-h", help="Bind host address"),
    port: int = typer.Option(8080, "--port", "-p", help="Bind port number"),
    reload: bool = typer.Option(False, "--reload", help="Enable uvicorn hot reloading")
):
    """Start the FastAPI HTTP service on local machine."""
    import uvicorn
    console.print(f"[bold green]Starting Azure IaC Generator service on http://{host}:{port}...[/bold green]")
    uvicorn.run("app.main:app", host=host, port=port, reload=reload)


if __name__ == "__main__":
    cli()
