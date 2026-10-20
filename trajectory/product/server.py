"""Authenticated HTTP surface. Every public operation is registered here once."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import os
import time
import uuid
from collections.abc import Callable
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from trajectory.product import VERSION
from trajectory.product.contracts import (
    AnalysisBatchRequest,
    AnalysisRequest,
    Batch,
    Correction,
    LostWindowRecomputeRequest,
    Price,
    RequestMeasurementRepair,
    SourceChunk,
    TaskEdit,
)
from trajectory.product.domain import Domain
from trajectory.product.error_logging import log_request_exception
from trajectory.product.schedules import (
    AnalysisAutomationGrant,
    ScheduleDelete,
    ScheduleRun,
    ScheduleWrite,
)
from trajectory.product.semantic import AnalysisResumeError, SemanticStore
from trajectory.product.semantic_runtime import AnalysisRuntime
from trajectory.product.stage_studies import StageStudies, StageStudyImport


@dataclass(frozen=True)
class Principal:
    account: str
    machine_client: str | None = None
    key_id: str | None = None
    scopes: tuple[str, ...] = ()


class CollectorBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    machine: uuid.UUID
    machine_client: str = Field(min_length=1, max_length=200)
    collector: str = Field(min_length=1, max_length=100)


OPERATIONS: list[dict[str, Any]] = [
    {
        "id": "analysis_automation_grant_list",
        "method": "GET",
        "path": "/api/analysis-automation-grants",
        "scope": "configure",
        "effect": "Read this owner's explicit analysis automation delegations. "
        "Native callers keep their real UUID and client; resource_owner selects "
        "the delegated domain.",
    },
    {
        "id": "analysis_automation_grant_write",
        "method": "POST",
        "path": "/api/analysis-automation-grants",
        "scope": "configure",
        "required_scopes": ["configure", "read_all"],
        "input": AnalysisAutomationGrant,
        "effect": "An authenticated human operator grants/revokes one verified "
        "native machine/client "
        "analysis access to their own resource domain. Revision checked and idempotent. "
        "Only session/analysis/task/schedule operations accept resource_owner; ledger, price, "
        "collector and backup privileges are never delegated by this grant.",
    },
    {
        "id": "analysis_schedule_delete",
        "method": "DELETE",
        "path": "/api/analysis-schedules/{schedule_id}",
        "scope": "configure",
        "input": ScheduleDelete,
        "effect": "Revision-checked archival disables a plan while "
        "preserving sampling evidence and paid job receipts. Does not cancel running model calls.",
    },
    {
        "id": "analysis_schedule_list",
        "method": "GET",
        "path": "/api/analysis-schedules",
        "scope": "read",
        "effect": "List account-owned daily sampling plans, next local slot, "
        "auditable selection runs and existing batch receipts; no model calls.",
    },
    {
        "id": "analysis_schedule_write",
        "method": "POST",
        "path": "/api/analysis-schedules",
        "scope": "configure",
        "input": ScheduleWrite,
        "effect": "Create or update a revision-checked daily plan, including enable/disable, "
        "directory subtrees, IANA timezone/local time, daily count, quiet/recent windows, "
        "operation-count weighted sampling and operation budget guard. Enabling authorizes "
        "paid Jindu analysis of future eligible snapshots. Today's overdue slot catches up once; "
        "older days are skipped. Enabling after the daily time starts tomorrow. "
        "Changing a plan never replays today's completed daily slot.",
    },
    {
        "id": "analysis_schedule_preview",
        "method": "GET",
        "path": "/api/analysis-schedules/{schedule_id}/candidates",
        "scope": "read",
        "effect": "Read eligible revision-pinned session snapshots, length weights and all "
        "exclusion reasons. Read-only; inactivity is a content/activity quiet-window proxy, "
        "not proof that a frontend process is closed. Image byte size does not affect weight.",
    },
    {
        "id": "analysis_schedule_run_read",
        "method": "GET",
        "path": "/api/analysis-schedules/{schedule_id}/runs/{run_id}",
        "scope": "read",
        "effect": "Read one auditable draw: full candidate/exclusion snapshot, seed, pinned "
        "selected revisions and current paid-analysis batch receipts. No model calls.",
    },
    {
        "id": "analysis_schedule_run",
        "method": "POST",
        "path": "/api/analysis-schedules/{schedule_id}/runs",
        "scope": "configure",
        "input": ScheduleRun,
        "effect": "Idempotently sample a manual batch without replacement "
        "using the same plan/domain rules. Incurs model usage. Pins immutable source revisions, "
        "records algorithm/seed/candidate exclusions, reuses existing queue and "
        "bounded concurrency. "
        "No automatic failed-job retries; uncertain calls require existing Jindu receipt review.",
    },
    {
        "id": "request_measurements_repair",
        "method": "POST",
        "path": "/api/request-measurements/repair",
        "scope": "upload",
        "input": RequestMeasurementRepair,
        "effect": "Idempotently migrate request origin/character measurements against exact "
        "durable source bytes using the current collector projector. Requires the bound native "
        "machine account and expected ledger/source revisions. Replaces only covered request "
        "events; preserves usage, collector checkpoints, paid analyses and study snapshots. "
        "Read source_progress first; source SHA-256 covers complete_bytes ending in newline.",
    },
    {
        "id": "stage_study_import",
        "method": "POST",
        "path": "/api/stage-studies",
        "scope": "configure",
        "input": StageStudyImport,
        "effect": "Idempotently import an immutable account-owned audited stage-label/measurement "
        "study; verifies saved task memberships and source/analysis revisions. No model calls "
        "or usage ledger writes. Changed content requires a new study ID.",
    },
    {
        "id": "stage_study_list",
        "method": "GET",
        "path": "/api/stage-studies",
        "scope": "read",
        "effect": "List account-owned stage segmentation/classification research studies.",
    },
    {
        "id": "stage_study_read",
        "method": "GET",
        "path": "/api/stage-studies/{study_id}",
        "scope": "read",
        "effect": "Read stage taxonomy, hierarchy, model confidence, mixed "
        "activity, metric availability and imported-session-record intervals (shared-native/fork "
        "dependence uncorrected). Filters: session_id, depth "
        "(1..100), node_kind=all|leaf|parent, tag, membership=direct|subtree, q, metric, "
        "confidence_min=0..1, mixed=all|mixed|single (threshold0.5). "
        "Metric coverage omits empty containers and retains measured zero. Subtree resource "
        "totals use a non-overlapping selected ancestor frontier. Classifier "
        "confidence, statistical intervals and unavailable human gold accuracy stay separate.",
    },
    {
        "id": "stage_study_stages",
        "method": "GET",
        "path": "/api/stage-studies/{study_id}/stages",
        "scope": "read",
        "effect": "Read revision-pinned stage label/metric detail and provenance. Same filters "
        "as stage_study_read; limit=1..500 default50, offset>=0. format=csv exports all filtered "
        "stages with confidence, secondary tags, parent/depth, Jindu call/receipt IDs; "
        "no model calls.",
    },
    {
        "id": "backup",
        "method": "POST",
        "path": "/api/backups",
        "scope": "backup",
        "input": AnalysisRequest,
        "effect": "Online SQLite domain export with durable file, directory and verified receipt",
    },
    {
        "id": "operation_read",
        "method": "GET",
        "path": "/api/sessions/{session_id}/operations/{operation_id}",
        "scope": "read",
        "effect": "Read one complete account-owned operation; source_revision pins the displayed "
        "immutable parsed snapshot. No model usage",
    },
    {
        "id": "source_evidence",
        "method": "GET",
        "path": "/api/sessions/{session_id}/operations/{operation_id}/evidence",
        "scope": "read",
        "effect": "Read bounded account-owned source evidence; optional source_revision pins the "
        "displayed immutable parsed snapshot and never starts parsing or analysis",
    },
    {
        "id": "source_append",
        "method": "POST",
        "path": "/api/source-chunks",
        "scope": "upload",
        "input": SourceChunk,
        "effect": "Durably append an authenticated source range; never duplicate usage",
    },
    {
        "id": "source_progress",
        "method": "GET",
        "path": "/api/source-progress",
        "scope": "upload",
        "effect": "Read bound source upload progress, without source content",
    },
    {
        "id": "sessions",
        "method": "GET",
        "path": "/api/sessions",
        "scope": "read",
        "effect": "Read normalized sessions and task-analysis availability",
    },
    {
        "id": "task_query",
        "method": "GET",
        "path": "/api/tasks",
        "scope": "read",
        "effect": "Query saved task titles and hierarchy across sessions without raw IR, "
        "execution text, metric recomputation or model calls. Filters: batch_id, session_id, "
        "cwd (directory subtree), q (case-insensitive title/id/ancestor search), depth "
        "(0=session root, 1=main phases); limit=1..500 default100, cursor from next_cursor. "
        "Restart pagination if query_revision changes. Results pin analysis/source revisions; "
        "batch results replaced by another source revision are explicitly skipped. "
        "Counts are direct operation memberships, not cost or elapsed time.",
    },
    {
        "id": "analysis_read",
        "method": "GET",
        "path": "/api/sessions/{session_id}/analysis",
        "scope": "read",
        "effect": "Read account-owned hierarchy and evidence; optional source_revision pins a "
        "retained snapshot. Default prefers active job input, then saved analysis input",
    },
    {
        "id": "session_parse",
        "method": "POST",
        "path": "/api/sessions/{session_id}/parse",
        "scope": "configure",
        "input": AnalysisRequest,
        "effect": "Idempotently refresh normalized IR from the durable source; no model usage",
    },
    {
        "id": "analysis_run",
        "method": "POST",
        "path": "/api/sessions/{session_id}/analysis",
        "scope": "configure",
        "input": AnalysisRequest,
        "effect": "Queue semantic segmentation using the configured model; incurs model usage",
    },
    {
        "id": "analysis_recompute_lost_window",
        "method": "POST",
        "path": "/api/analysis-jobs/{job_id}/recompute-lost-window",
        "scope": "configure",
        "input": LostWindowRecomputeRequest,
        "effect": "Explicit operator decision to recompute one lost-response window after Jindu "
        "receipt verification; may duplicate an unknown prior charge; never automatic retry",
    },
    {
        "id": "analysis_resume",
        "method": "POST",
        "path": "/api/analysis-jobs/{job_id}/resume",
        "scope": "configure",
        "input": AnalysisRequest,
        "effect": "Continue the same failed job from durable checkpoints, at most 3 resumes; "
        "new windows incur model usage, uncertain calls remain blocked",
    },
    {
        "id": "analysis_batch_run",
        "method": "POST",
        "path": "/api/analysis-batches",
        "scope": "configure",
        "input": AnalysisBatchRequest,
        "effect": "Idempotently queue account-owned sessions with bounded parallel model usage",
    },
    {
        "id": "analysis_batch_list",
        "method": "GET",
        "path": "/api/analysis-batches",
        "scope": "read",
        "effect": "Read the latest 50 account-owned analysis batches",
    },
    {
        "id": "analysis_batch_read",
        "method": "GET",
        "path": "/api/analysis-batches/{batch_id}",
        "scope": "read",
        "effect": "Read batch queue, progress, errors, elapsed time and model usage",
    },
    {
        "id": "task_edit",
        "method": "POST",
        "path": "/api/sessions/{session_id}/tasks",
        "scope": "configure",
        "input": TaskEdit,
        "effect": "Audit task rename, sibling merge or split and recalculate attribution",
    },
    {
        "id": "request_traces",
        "method": "GET",
        "path": "/api/request-traces",
        "scope": "read_all",
        "effect": "Read bounded request metadata and auth outcomes; no payloads or secrets",
    },
    {
        "id": "overview",
        "method": "GET",
        "path": "/api/overview",
        "scope": "read",
        "effect": "Read account usage, project attribution and evidence-based anomalies",
    },
    {
        "id": "platform",
        "method": "GET",
        "path": "/api/platform",
        "scope": "read_all",
        "effect": "Read all accounts for operational analysis",
    },
    {
        "id": "ingest",
        "method": "POST",
        "path": "/api/batches",
        "scope": "upload",
        "input": Batch,
        "effect": "Persist normalized records; return an idempotent durable receipt",
    },
    {
        "id": "bind",
        "method": "POST",
        "path": "/api/collectors",
        "scope": "configure",
        "input": CollectorBinding,
        "required_scopes": ["configure", "read_all"],
        "effect": "Bind a native machine collector to the authenticated owner",
    },
    {
        "id": "correct",
        "method": "POST",
        "path": "/api/corrections",
        "scope": "configure",
        "input": Correction,
        "effect": "Audit and apply an account-scoped task attribution correction",
    },
    {
        "id": "price",
        "method": "POST",
        "path": "/api/prices",
        "scope": "configure",
        "input": Price,
        "effect": (
            "Audit account-scoped historical or verified current reference rates, "
            "with optional context tiers"
        ),
    },
]


def native_authorizer(request: Request, scope: str | None) -> Principal:
    # Production has no standalone auth fallback, including requests from loopback.
    if not os.environ.get("BATCAVE_AUTHORITY_CONFIG"):
        request.state.auth_outcome = "authority_unconfigured"
        raise HTTPException(503, "Native account authority is not configured")
    from batcave_http.auth import registered_key
    from batcave_http.authority import account_allowed

    authorization = request.headers.get("authorization", "")
    if authorization:
        entry = registered_key(authorization, "trajectory", None)
        if not entry:
            request.state.auth_outcome = "credential_unrecognized"
            raise HTTPException(403, "Credential denied")
        if not account_allowed(
            entry["account_id"],
            "trajectory",
            entry.get("machine_client_id"),
            required_scope=None,
        ):
            request.state.auth_outcome = "account_or_authority_unavailable"
            raise HTTPException(403, "Account, client or key permission denied")
        principal = Principal(
            entry["account_id"],
            entry.get("machine_client_id"),
            entry.get("key_id"),
            tuple(entry.get("scopes", [])),
        )
        request.state.principal = principal
        if scope is not None and scope not in principal.scopes:
            request.state.auth_outcome = "scope_denied"
            raise HTTPException(403, "Key scope denied")
        if scope in {"read_all", "backup"} and not account_allowed(
            principal.account, "trajectory", principal.machine_client, required_scope=scope
        ):
            request.state.auth_outcome = "privilege_denied"
            raise HTTPException(403, "Current account privilege denied")
        return principal
    ingress = os.environ.get("TRAJECTORY_INGRESS_SECRET", "")
    supplied = request.headers.get("x-batcave-ingress", "")
    if not ingress or not hmac.compare_digest(ingress.encode(), supplied.encode()):
        request.state.auth_outcome = "ingress_untrusted"
        raise HTTPException(401, "Authentication required")
    try:
        account = str(uuid.UUID(request.headers.get("x-forwarded-user", "")))
    except ValueError as error:
        raise HTTPException(401, "Authentication required") from error
    request.state.principal = Principal(account)
    if not account_allowed(
        account, "trajectory", required_scope=scope if scope in {"read_all", "backup"} else None
    ):
        raise HTTPException(403, "Service permission denied")
    if scope == "upload":
        raise HTTPException(403, "Uploads require a native machine account key")
    scopes: tuple[str, ...] = ("read", "configure")
    if scope == "read_all" or (
        scope is None and account_allowed(account, "trajectory", required_scope="read_all")
    ):
        scopes += ("read_all",)
    return Principal(account, scopes=scopes)


def create_app(
    path: Path,
    authorizer: Callable[[Request, str | None], Principal] = native_authorizer,
    machine_verifier: Callable[[str, str], bool] | None = None,
    resource_owner_verifier: Callable[[str], bool] | None = None,
) -> FastAPI:
    domain = Domain(path)
    semantic = SemanticStore(domain)
    studies = StageStudies(domain)
    runtime = AnalysisRuntime(semantic)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> Any:
        async def consume() -> None:
            while True:
                await asyncio.to_thread(runtime.tick)
                await asyncio.sleep(1)

        task = asyncio.create_task(consume())
        try:
            yield
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
            await asyncio.to_thread(runtime.close)

    app = FastAPI(
        title="BatCave Trajectory",
        version=VERSION,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.state.domain = domain
    app.state.semantic = semantic
    app.state.stage_studies = studies
    app.state.analysis_runtime = runtime
    original_authorizer = authorizer

    def tracked_authorizer(request: Request, scope: str | None) -> Principal:
        principal = original_authorizer(request, scope)
        request.state.principal = principal
        return principal

    authorizer = tracked_authorizer

    @app.middleware("http")
    async def request_trace(request: Request, call_next: Any) -> Any:
        started = time.perf_counter()
        identifier = uuid.uuid4().hex
        request.state.auth_outcome = "unconfirmed"
        try:
            response = await call_next(request)
        except Exception as error:
            log_request_exception(identifier, error)
            request.state.auth_outcome = "internal_error"
            response = JSONResponse(
                {"error": "Request failed", "request_id": identifier}, status_code=500
            )
        principal = getattr(request.state, "principal", None)
        account = None
        if principal:
            try:
                account = str(uuid.UUID(principal.account))
            except ValueError:
                pass
        route = next(
            (
                getattr(route, "path", "")
                for route in app.routes
                if getattr(route, "path", "") == request.url.path
            ),
            "/trajectory/:unknown",
        )
        public = route in {"/trajectory/health", "/trajectory/help", "/trajectory/protocol"}
        outcome = getattr(request.state, "auth_outcome", "unconfirmed")
        if response.status_code < 400:
            outcome = "authenticated" if account else "public" if public else "unconfirmed"
        elif outcome == "unconfirmed":
            outcome = (
                "permission_denied"
                if account and response.status_code == 403
                else (
                    "authentication_failed"
                    if response.status_code in {401, 403}
                    else "request_failed"
                )
            )
        record = {
            "request_id": identifier,
            "account_id": account,
            "key_id": principal.key_id if account and principal is not None else None,
            "machine_client": (
                principal.machine_client if account and principal is not None else None
            ),
            "source": (
                "machine"
                if account and principal is not None and principal.machine_client
                else (
                    "account"
                    if account
                    else (
                        "public_health"
                        if route == "/trajectory/health"
                        else "public_discovery" if public else "unconfirmed"
                    )
                )
            ),
            "authentication_outcome": outcome,
            "method": request.method,
            "route": route,
            "status": response.status_code,
            "duration_ms": round((time.perf_counter() - started) * 1000, 3),
        }
        await asyncio.to_thread(domain.trace, record)
        response.headers["X-BatCave-Request-ID"] = identifier
        if account:
            response.headers["X-BatCave-Account"] = account
        from batcave_http.telemetry import emit

        emit(
            "trajectory",
            account,
            route,
            request.method,
            response.status_code,
            record["duration_ms"],
            None,
            identifier,
            time.time(),
            key_id=record["key_id"],
            client_id=record["machine_client"],
        )
        return response

    @app.get("/trajectory/health")
    def health(request: Request) -> dict[str, str]:
        if request.headers.get("authorization"):
            authorizer(request, None)
        return {"service": "trajectory", "version": VERSION, "status": "ready"}

    @app.get("/trajectory/help")
    def help_document(request: Request) -> dict[str, Any]:
        from batcave_http.discovery import anonymous, public_help

        if anonymous(request.headers):
            bootstrap: dict[str, Any] = public_help("trajectory", "/trajectory")
            return bootstrap
        principal = authorizer(request, None)
        return {
            "service": "trajectory",
            "version": VERSION,
            "transport": "http",
            "api_base": "/trajectory",
            "protocol": "trajectory-batch/1",
            "caller": {"account_id": principal.account, "machine_client": principal.machine_client},
            "scopes": list(principal.scopes),
            "tools": [
                {
                    "name": op["id"],
                    "method": op["method"],
                    "path": "/trajectory" + str(op["path"]),
                    "api_path": op["path"],
                    "scope": op["scope"],
                    "required_scopes": op.get("required_scopes", [op["scope"]]),
                    "description": op["effect"],
                    "input_schema": op["input"].model_json_schema() if "input" in op else None,
                }
                for op in OPERATIONS
                if set(op.get("required_scopes", [op["scope"]])) <= set(principal.scopes)
            ],
        }

    @app.get("/trajectory/protocol")
    def protocol(request: Request) -> dict[str, Any]:
        if request.headers.get("authorization"):
            authorizer(request, None)
        return Batch.model_json_schema()

    def endpoint(operation: dict[str, Any]) -> Callable[..., Any]:
        async def execute(request: Request) -> Any:
            principal = authorizer(request, str(operation["scope"]))
            for additional_scope in operation.get("required_scopes", []):
                if additional_scope != operation["scope"]:
                    authorizer(request, additional_scope)
            identifier = operation["id"]
            resource_owner = principal.account
            requested_owner = request.query_params.get("resource_owner")
            if requested_owner and requested_owner != principal.account:
                delegatable = {
                    "sessions",
                    "task_query",
                    "analysis_read",
                    "operation_read",
                    "source_evidence",
                    "analysis_run",
                    "analysis_batch_run",
                    "analysis_batch_list",
                    "analysis_batch_read",
                    "analysis_resume",
                    "analysis_recompute_lost_window",
                    "analysis_schedule_list",
                    "analysis_schedule_write",
                    "analysis_schedule_preview",
                    "analysis_schedule_run",
                    "analysis_schedule_run_read",
                    "analysis_schedule_delete",
                }
                if identifier not in delegatable:
                    raise HTTPException(403, "Operation does not support analysis delegation")
                try:
                    resource_owner = runtime.schedules.resolve_owner(
                        principal.account, principal.machine_client, requested_owner
                    )
                except PermissionError as error:
                    raise HTTPException(403, str(error)) from error
                if resource_owner_verifier is None:
                    from batcave_http.authority import account_allowed

                    owner_active = account_allowed(resource_owner, "trajectory")
                else:
                    owner_active = resource_owner_verifier(resource_owner)
                if not owner_active:
                    raise HTTPException(403, "Resource owner unavailable")
                request.state.resource_owner = resource_owner
            try:
                if identifier == "analysis_automation_grant_list":
                    if principal.machine_client:
                        raise HTTPException(403, "Delegation administration requires an operator")
                    return await asyncio.to_thread(runtime.schedules.grants, principal.account)
                if identifier == "analysis_schedule_list":
                    return await asyncio.to_thread(runtime.schedules.catalog, resource_owner)
                if identifier == "analysis_schedule_run_read":
                    return await asyncio.to_thread(
                        runtime.schedules.run_detail,
                        resource_owner,
                        request.path_params["schedule_id"],
                        request.path_params["run_id"],
                    )
                if identifier == "analysis_schedule_preview":
                    return await asyncio.to_thread(
                        runtime.schedules.preview,
                        resource_owner,
                        request.path_params["schedule_id"],
                    )
                if identifier == "stage_study_list":
                    return await asyncio.to_thread(studies.catalog, resource_owner)
                if identifier in {"stage_study_read", "stage_study_stages"}:
                    filters = dict(request.query_params)
                    study = request.path_params["study_id"]
                    if identifier == "stage_study_stages" and filters.get("format") == "csv":
                        csv_body = await asyncio.to_thread(
                            studies.csv, resource_owner, study, filters
                        )
                        return Response(
                            csv_body,
                            media_type="text/csv; charset=utf-8",
                            headers={"Content-Disposition": "attachment; filename=stage-study.csv"},
                        )
                    reader = studies.summary if identifier == "stage_study_read" else studies.stages
                    return await asyncio.to_thread(reader, resource_owner, study, filters)
                if identifier == "request_traces":
                    return await asyncio.to_thread(domain.traces)
                if identifier == "source_progress":
                    if not principal.machine_client:
                        raise HTTPException(
                            403, "Source progress requires a native machine account"
                        )
                    return await asyncio.to_thread(
                        semantic.source_progress,
                        resource_owner,
                        request.query_params.get("collector", ""),
                        request.query_params.get("source", ""),
                    )
                if identifier == "sessions":
                    return await asyncio.to_thread(
                        semantic.sessions,
                        resource_owner,
                        request.query_params.get("project", ""),
                        request.query_params.get("since", ""),
                        request.query_params.get("until", ""),
                        analysis_status=request.query_params.get("analysis_status", "all"),
                        cwd=request.query_params.get("cwd", ""),
                        sort=request.query_params.get("sort", "last_activity_desc"),
                        q=request.query_params.get("q", ""),
                        limit=int(request.query_params.get("limit", "0")),
                        cursor=request.query_params.get("cursor", ""),
                    )
                if identifier == "task_query":
                    return await asyncio.to_thread(
                        semantic.task_query,
                        resource_owner,
                        batch_id=request.query_params.get("batch_id", ""),
                        session_id=request.query_params.get("session_id", ""),
                        cwd=request.query_params.get("cwd", ""),
                        q=request.query_params.get("q", ""),
                        depth=(
                            int(request.query_params["depth"])
                            if "depth" in request.query_params
                            else None
                        ),
                        limit=int(request.query_params.get("limit", "100")),
                        cursor=request.query_params.get("cursor", ""),
                    )
                if identifier == "analysis_batch_list":
                    return await asyncio.to_thread(semantic.batches, resource_owner)
                if identifier == "analysis_batch_read":
                    return await asyncio.to_thread(
                        semantic.batch_detail, resource_owner, request.path_params["batch_id"]
                    )
                if identifier == "analysis_read":
                    detail = await asyncio.to_thread(
                        semantic.detail,
                        resource_owner,
                        request.path_params["session_id"],
                        source_revision=request.query_params.get("source_revision") or None,
                    )
                    return {
                        **detail,
                        "operations": [
                            {
                                **{key: value for key, value in operation.items() if key != "text"},
                                "body_available": operation.get("text") is not None,
                            }
                            for operation in detail.get("operations", [])
                        ],
                    }
                if identifier == "operation_read":
                    return await asyncio.to_thread(
                        semantic.operation,
                        resource_owner,
                        request.path_params["session_id"],
                        request.path_params["operation_id"],
                        source_revision=request.query_params.get("source_revision") or None,
                    )
                if identifier == "source_evidence":
                    return await asyncio.to_thread(
                        semantic.evidence,
                        resource_owner,
                        request.path_params["session_id"],
                        request.path_params["operation_id"],
                        source_revision=request.query_params.get("source_revision") or None,
                    )
                if identifier in ("overview", "platform"):
                    return await asyncio.to_thread(
                        domain.overview,
                        resource_owner if identifier == "overview" else None,
                        request.query_params.get("since", ""),
                        request.query_params.get("until", ""),
                    )
                if request.headers.get("origin") and request.headers["origin"] != os.environ.get(
                    "TRAJECTORY_PUBLIC_ORIGIN"
                ):
                    raise HTTPException(403, "Origin denied")
                length = int(request.headers.get("content-length", "0"))
                if length <= 0 or length > 4 * 1024 * 1024:
                    raise HTTPException(413, "Batch size exceeds limit")
                chunks = bytearray()
                async for chunk in request.stream():
                    if len(chunks) + len(chunk) > 4 * 1024 * 1024:
                        raise HTTPException(413, "Batch size exceeds limit")
                    chunks.extend(chunk)
                body = bytes(chunks)
                value = operation["input"].model_validate_json(body)
                if identifier == "stage_study_import":
                    return await asyncio.to_thread(studies.import_study, resource_owner, value)
                if identifier == "backup":
                    return await asyncio.to_thread(
                        domain.online_backup, resource_owner, value.mutation_id
                    )
                if identifier == "request_measurements_repair":
                    if not principal.machine_client:
                        raise HTTPException(403, "Request repair requires a native machine account")
                    return await asyncio.to_thread(
                        domain.repair_requests,
                        resource_owner,
                        value,
                        principal.key_id,
                        principal.machine_client,
                    )
                if identifier == "source_append":
                    if not principal.machine_client:
                        raise HTTPException(403, "Uploads require a native machine account")
                    return await asyncio.to_thread(semantic.ingest_source, resource_owner, value)
                if identifier == "analysis_recompute_lost_window":
                    return await asyncio.to_thread(
                        semantic.recompute_lost_window,
                        resource_owner,
                        request.path_params["job_id"],
                        value,
                        {
                            "account_id": principal.account,
                            "key_id": principal.key_id,
                            "machine_client": principal.machine_client,
                        },
                    )
                if identifier == "analysis_resume":
                    return await asyncio.to_thread(
                        semantic.resume_analysis,
                        resource_owner,
                        request.path_params["job_id"],
                        value,
                    )
                if identifier == "analysis_automation_grant_write":
                    if principal.machine_client:
                        raise HTTPException(403, "Delegation administration requires an operator")
                    if machine_verifier is None:
                        from batcave_http.authority import account_allowed

                        allowed = account_allowed(
                            str(value.machine), "trajectory", value.machine_client
                        )
                    else:
                        allowed = machine_verifier(str(value.machine), value.machine_client)
                    if value.enabled and not allowed:
                        raise HTTPException(403, "Native machine/client is unavailable")
                    return await asyncio.to_thread(
                        runtime.schedules.grant, principal.account, value
                    )
                if identifier == "analysis_schedule_delete":
                    return await asyncio.to_thread(
                        runtime.schedules.remove,
                        resource_owner,
                        request.path_params["schedule_id"],
                        value,
                        {
                            "account_id": principal.account,
                            "key_id": principal.key_id,
                            "machine_client": principal.machine_client,
                        },
                    )
                if identifier == "analysis_schedule_write":
                    return await asyncio.to_thread(
                        runtime.schedules.write,
                        resource_owner,
                        value,
                        {
                            "account_id": principal.account,
                            "key_id": principal.key_id,
                            "machine_client": principal.machine_client,
                        },
                    )
                if identifier == "analysis_schedule_run":
                    return await asyncio.to_thread(
                        runtime.schedules.run,
                        resource_owner,
                        request.path_params["schedule_id"],
                        value,
                        {
                            "account_id": principal.account,
                            "key_id": principal.key_id,
                            "machine_client": principal.machine_client,
                        },
                    )
                if identifier == "analysis_batch_run":
                    return await asyncio.to_thread(semantic.request_batch, resource_owner, value)
                if identifier == "session_parse":
                    return await asyncio.to_thread(
                        semantic.request_parse,
                        resource_owner,
                        request.path_params["session_id"],
                        value,
                    )
                if identifier == "analysis_run":
                    return await asyncio.to_thread(
                        semantic.request_analysis,
                        resource_owner,
                        request.path_params["session_id"],
                        value,
                    )
                if identifier == "task_edit":
                    return await asyncio.to_thread(
                        semantic.edit_task,
                        resource_owner,
                        request.path_params["session_id"],
                        value,
                    )
                if identifier == "ingest":
                    if not principal.machine_client:
                        raise HTTPException(403, "Uploads require a native machine account")
                    return await asyncio.to_thread(
                        domain.ingest,
                        resource_owner,
                        value,
                        principal.key_id,
                        principal.machine_client,
                    )
                if identifier == "bind":
                    if principal.machine_client:
                        raise HTTPException(
                            403,
                            "Collector ownership requires an authenticated operator",
                        )
                    if machine_verifier is None:
                        from batcave_http.authority import account_allowed

                        allowed = account_allowed(
                            str(value.machine), "trajectory", value.machine_client
                        )
                    else:
                        allowed = machine_verifier(str(value.machine), value.machine_client)
                    if not allowed:
                        raise HTTPException(403, "Native collector account denied")
                    return await asyncio.to_thread(
                        domain.register, resource_owner, str(value.machine), value.collector
                    )
                if identifier == "correct":
                    return await asyncio.to_thread(domain.correct, resource_owner, value)
                if identifier == "price":
                    return await asyncio.to_thread(domain.price, resource_owner, value)
            except ValidationError as error:
                raise HTTPException(422, "Invalid protocol payload") from error
            except PermissionError as error:
                raise HTTPException(403, str(error)) from error
            except AnalysisResumeError as error:
                raise HTTPException(409, {"code": error.code, "message": str(error)}) from error
            except ValueError as error:
                raise HTTPException(409, str(error)) from error
            raise HTTPException(404, "Unknown operation")

        return execute

    for operation in OPERATIONS:
        app.add_api_route(
            "/trajectory" + str(operation["path"]),
            endpoint(operation),
            methods=[str(operation["method"])],
            name=str(operation["id"]),
        )

    web_root = Path(__file__).parent
    web_assets = {
        name: (web_root / name).read_bytes()
        for name in ("research.js", "research.css", "schedules.js", "schedules.css")
    }
    research_revision = hashlib.sha256(
        web_assets["research.js"] + b"\0" + web_assets["research.css"]
    ).hexdigest()[:16]
    schedule_revision = hashlib.sha256(
        web_assets["schedules.js"] + b"\0" + web_assets["schedules.css"]
    ).hexdigest()[:16]

    @app.get("/trajectory/", response_class=HTMLResponse)
    def dashboard(request: Request) -> str:
        authorizer(request, "read")
        return (
            (web_root / "dashboard.html")
            .read_text()
            .replace("__TRAJECTORY_RESEARCH_REVISION__", research_revision)
            .replace("__TRAJECTORY_SCHEDULE_REVISION__", schedule_revision)
        )

    @app.get("/trajectory/schedules.js")
    @app.get("/trajectory/schedules.css")
    @app.get("/trajectory/research.js")
    @app.get("/trajectory/research.css")
    def web_asset(request: Request) -> Response:
        authorizer(request, "read")
        filename = request.url.path.rsplit("/", 1)[-1]
        body = web_assets[filename]
        etag = '"' + hashlib.sha256(body).hexdigest() + '"'
        headers = {"Cache-Control": "private, no-cache", "ETag": etag, "Vary": "Authorization"}
        matches = request.headers.get("If-None-Match", "").split(",")
        if any(tag.strip().removeprefix("W/") in (etag, "*") for tag in matches):
            return Response(status_code=304, headers=headers)
        return Response(
            body,
            media_type="text/javascript" if filename.endswith(".js") else "text/css",
            headers=headers,
        )

    return app


def main() -> None:
    import uvicorn

    app = create_app(
        Path(os.environ.get("TRAJECTORY_DB", "/var/lib/batcave-trajectory/trajectory.db"))
    )
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=int(os.environ.get("TRAJECTORY_PORT", "18895")),
        access_log=False,
    )


if __name__ == "__main__":
    main()
