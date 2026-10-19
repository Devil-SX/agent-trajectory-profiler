"""Authenticated HTTP surface. Every public operation is registered here once."""

from __future__ import annotations

import asyncio
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
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from trajectory.product import VERSION
from trajectory.product.contracts import (
    AnalysisBatchRequest,
    AnalysisRequest,
    Batch,
    Correction,
    LostWindowRecomputeRequest,
    Price,
    SourceChunk,
    TaskEdit,
)
from trajectory.product.domain import Domain
from trajectory.product.error_logging import log_request_exception
from trajectory.product.semantic import AnalysisResumeError, SemanticStore
from trajectory.product.semantic_runtime import AnalysisRuntime


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
        "id": "backup",
        "method": "POST",
        "path": "/api/backups",
        "scope": "backup",
        "input": AnalysisRequest,
        "effect": "Online SQLite domain export with durable file, directory and verified receipt",
    },
    {
        "id": "source_evidence",
        "method": "GET",
        "path": "/api/sessions/{session_id}/operations/{operation_id}/evidence",
        "scope": "read",
        "effect": "Read a bounded account-owned original source record for an operation",
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
        "id": "analysis_read",
        "method": "GET",
        "path": "/api/sessions/{session_id}/analysis",
        "scope": "read",
        "effect": "Read task hierarchy, measured costs and account-owned source evidence",
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
) -> FastAPI:
    domain = Domain(path)
    semantic = SemanticStore(domain)
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
            try:
                if identifier == "request_traces":
                    return await asyncio.to_thread(domain.traces)
                if identifier == "source_progress":
                    if not principal.machine_client:
                        raise HTTPException(
                            403, "Source progress requires a native machine account"
                        )
                    return await asyncio.to_thread(
                        semantic.source_progress,
                        principal.account,
                        request.query_params.get("collector", ""),
                        request.query_params.get("source", ""),
                    )
                if identifier == "sessions":
                    return await asyncio.to_thread(
                        semantic.sessions,
                        principal.account,
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
                if identifier == "analysis_batch_list":
                    return await asyncio.to_thread(semantic.batches, principal.account)
                if identifier == "analysis_batch_read":
                    return await asyncio.to_thread(
                        semantic.batch_detail, principal.account, request.path_params["batch_id"]
                    )
                if identifier == "analysis_read":
                    return await asyncio.to_thread(
                        semantic.detail, principal.account, request.path_params["session_id"]
                    )
                if identifier == "source_evidence":
                    return await asyncio.to_thread(
                        semantic.evidence,
                        principal.account,
                        request.path_params["session_id"],
                        request.path_params["operation_id"],
                    )
                if identifier in ("overview", "platform"):
                    return await asyncio.to_thread(
                        domain.overview,
                        principal.account if identifier == "overview" else None,
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
                if identifier == "backup":
                    return await asyncio.to_thread(
                        domain.online_backup, principal.account, value.mutation_id
                    )
                if identifier == "source_append":
                    if not principal.machine_client:
                        raise HTTPException(403, "Uploads require a native machine account")
                    return await asyncio.to_thread(semantic.ingest_source, principal.account, value)
                if identifier == "analysis_recompute_lost_window":
                    return await asyncio.to_thread(
                        semantic.recompute_lost_window,
                        principal.account,
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
                        principal.account,
                        request.path_params["job_id"],
                        value,
                    )
                if identifier == "analysis_batch_run":
                    return await asyncio.to_thread(semantic.request_batch, principal.account, value)
                if identifier == "session_parse":
                    return await asyncio.to_thread(
                        semantic.request_parse,
                        principal.account,
                        request.path_params["session_id"],
                        value,
                    )
                if identifier == "analysis_run":
                    return await asyncio.to_thread(
                        semantic.request_analysis,
                        principal.account,
                        request.path_params["session_id"],
                        value,
                    )
                if identifier == "task_edit":
                    return await asyncio.to_thread(
                        semantic.edit_task,
                        principal.account,
                        request.path_params["session_id"],
                        value,
                    )
                if identifier == "ingest":
                    if not principal.machine_client:
                        raise HTTPException(403, "Uploads require a native machine account")
                    return await asyncio.to_thread(
                        domain.ingest,
                        principal.account,
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
                        domain.register, principal.account, str(value.machine), value.collector
                    )
                if identifier == "correct":
                    return await asyncio.to_thread(domain.correct, principal.account, value)
                if identifier == "price":
                    return await asyncio.to_thread(domain.price, principal.account, value)
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

    @app.get("/trajectory/", response_class=HTMLResponse)
    def dashboard(request: Request) -> str:
        authorizer(request, "read")
        return (Path(__file__).parent / "dashboard.html").read_text()

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
