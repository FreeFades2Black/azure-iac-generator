import os
import shutil
from pathlib import Path
from fastapi import FastAPI, HTTPException, status, Query, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.models.schemas import (
    InfrastructureBuildRequest,
    BuildResponse,
    PublishResponse,
    HealthResponse,
)
from app.engine.generator import render_and_validate, render_artifacts
from app.engine.validator import (
    PipelineError,
    ComplianceViolationError,
    SecurityValidator,
    check_tool_availability,
    validate_artifacts,
)
from app.engine.git_publisher import push_to_github

app = FastAPI(
    title="Azure Resilient IaC and Configuration Generator",
    description=(
        "Production API service to ingest infrastructure parameters, strictly validate multi-region constraints, "
        "render resilient Azure Terraform HCL & Ansible playbooks, enforce sandboxed security gates, and publish to GitHub."
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

validator = SecurityValidator()

# Enable CORS for local Omarchy dashboard/UI integrations
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(ComplianceViolationError)
async def compliance_violation_handler(request, exc: ComplianceViolationError):
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "status": "failed_compliance_gate",
            "error": str(exc),
            "violations": exc.violations,
        },
    )


@app.exception_handler(PipelineError)
async def pipeline_error_handler(request, exc: PipelineError):
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"status": "error", "error_type": "PipelineError", "detail": str(exc)},
    )


@app.exception_handler(RuntimeError)
async def runtime_error_handler(request, exc: RuntimeError):
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"status": "error", "error_type": "RuntimeError", "detail": str(exc)},
    )


@app.get("/health", response_model=HealthResponse, tags=["Health"])
async def health_check():
    """System health check and local toolchain discovery."""
    return HealthResponse(
        status="ok",
        service="azure-iac-generator",
        version="1.0.0",
        tools_available=check_tool_availability(),
    )


@app.post("/api/v1/generate", response_model=BuildResponse, tags=["IaC Generator"])
async def generate_iac(
    request: InfrastructureBuildRequest,
    run_validation: bool = Query(True, description="Execute linter quality gates"),
    strict_validation: bool = Query(False, description="Fail if linters are not installed in PATH")
):
    """
    Ingest infrastructure configuration, render Terraform HCL and Ansible playbooks,
    run automated quality gates, and output build artifacts.
    """
    try:
        build_dir = render_and_validate(
            request=request,
            run_validation=run_validation,
            strict_validation=strict_validation
        )

        # Collect file manifest
        manifest: list[str] = []
        for root, _, files in os.walk(build_dir):
            for file in files:
                rel_path = os.path.relpath(os.path.join(root, file), build_dir)
                manifest.append(rel_path.replace("\\", "/"))

        manifest.sort()

        validation_logs: list[str] = []
        scan_results: dict | None = None
        if run_validation:
            validation_logs = validate_artifacts(build_dir, strict=strict_validation)
            if validator.is_available:
                scan_results = validator.scan_terraform_directory(os.path.join(build_dir, "terraform"))

        return BuildResponse(
            status="success",
            message=f"IaC artifacts successfully generated for {request.project_name}",
            project_name=request.project_name,
            redundancy=request.redundancy,
            primary_region=request.primary_region,
            secondary_region=request.secondary_region,
            output_dir=build_dir,
            manifest=manifest,
            validation_passed=True,
            validation_details=validation_logs,
            compliance_scan=scan_results
        )
    except ComplianceViolationError:
        raise
    except PipelineError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Validation pipeline rejected artifact: {e}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Generation failed: {str(e)}"
        )


@app.post("/api/v1/validate", tags=["IaC Generator"])
async def validate_iac(
    request: InfrastructureBuildRequest,
    strict: bool = Query(False, description="Enforce that linters must be installed")
):
    """
    Dry-run validation: Renders templates into temporary directory, runs syntax/security scans,
    and cleans up without persisting artifacts.
    """
    build_dir = None
    try:
        build_dir = render_and_validate(
            request=request,
            run_validation=False
        )
        logs = validate_artifacts(build_dir, strict=strict)
        return {
            "status": "valid",
            "project_name": request.project_name,
            "redundancy": request.redundancy.value,
            "storage_replication": request.storage_replication_type,
            "secondary_region": request.secondary_region,
            "quality_gate_logs": logs
        }
    finally:
        if build_dir and os.path.exists(build_dir):
            shutil.rmtree(build_dir, ignore_errors=True)


@app.post("/api/v1/publish", response_model=PublishResponse, tags=["GitHub Publisher"])
async def publish_iac(
    request: InfrastructureBuildRequest,
    run_validation: bool = Query(True),
    x_github_token: str | None = Header(None, alias="X-GitHub-Token")
):
    """
    Renders, validates, and pushes the generated IaC repository directly to GitHub.
    Uses token from X-GitHub-Token header or host GITHUB_TOKEN environment variable.
    """
    token = x_github_token or os.environ.get("GITHUB_TOKEN")
    if not token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="GITHUB_TOKEN not provided in X-GitHub-Token header or host environment."
        )

    build_dir = render_and_validate(
        request=request,
        run_validation=run_validation,
        strict_validation=False
    )

    try:
        repo_url = push_to_github(build_dir, request, token=token)
        return PublishResponse(
            status="success",
            message=f"Repository published to {repo_url}",
            github_repo_url=repo_url,
            branch="main",
            commit_message=f"Initial automated release for {request.project_name} ({request.redundancy.value})"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"GitHub publishing failed: {str(e)}"
        )
    finally:
        # Cleanup temporary build folder after publish
        shutil.rmtree(build_dir, ignore_errors=True)
