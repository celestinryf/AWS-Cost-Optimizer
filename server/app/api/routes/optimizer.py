from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query, status

from app.dependencies import execution_service, rollback_service, run_store, scanner_service, scoring_service
from app.models import (
    ExecutionAuditRecord,
    ExecuteRequest,
    ExecuteResponse,
    RollbackActionStatus,
    RollbackRequest,
    RollbackResponse,
    RollbackStatus,
    RunDetails,
    RunSummary,
    ScanRequest,
    ScanResponse,
    ScoreRequest,
    ScoreResponse,
)


router = APIRouter()


@router.post("/scan", response_model=ScanResponse, status_code=status.HTTP_201_CREATED)
def scan(request: ScanRequest) -> ScanResponse:
    recommendations = scanner_service.scan(request)
    record = run_store.create(recommendations)
    estimated_monthly_savings = sum(
        recommendation.estimated_monthly_savings for recommendation in recommendations
    )

    return ScanResponse(
        run_id=record.run_id,
        status=record.status,
        recommendations=recommendations,
        estimated_monthly_savings=estimated_monthly_savings,
        scanned_at=datetime.now(timezone.utc),
    )


@router.post("/score", response_model=ScoreResponse)
def score(request: ScoreRequest) -> ScoreResponse:
    record = run_store.get(request.run_id)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Run '{request.run_id}' was not found.",
        )

    scoring_result = scoring_service.score(record.recommendations)
    updated = run_store.set_scores(
        request.run_id,
        scoring_result.scores,
        scoring_result.savings_details,
        scoring_result.savings_summary,
    )
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Run '{request.run_id}' was not found.",
        )

    safe_to_automate = len([item for item in scoring_result.scores if item.safe_to_automate])
    requires_approval = len([item for item in scoring_result.scores if item.requires_approval])

    return ScoreResponse(
        run_id=updated.run_id,
        status=updated.status,
        scores=scoring_result.scores,
        savings_details=scoring_result.savings_details,
        savings_summary=scoring_result.savings_summary,
        safe_to_automate=safe_to_automate,
        requires_approval=requires_approval,
        scored_at=datetime.now(timezone.utc),
    )


@router.post("/execute", response_model=ExecuteResponse)
def execute(request: ExecuteRequest) -> ExecuteResponse:
    record = run_store.get(request.run_id)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Run '{request.run_id}' was not found.",
        )

    if not record.scores:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Run has not been scored. Call /optimizer/score first.",
        )

    result = execution_service.execute(request, record.recommendations, record.scores)
    updated = run_store.set_execution(request.run_id, result)
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Run '{request.run_id}' was not found.",
        )

    return result


@router.post("/rollback", response_model=RollbackResponse)
def rollback(request: RollbackRequest) -> RollbackResponse:
    record = run_store.get(request.run_id)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Run '{request.run_id}' was not found.",
        )

    execution_id = request.execution_id
    if not execution_id:
        if not record.execution:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Run has no execution batch to rollback.",
            )
        execution_id = record.execution.execution_id

    audit_records = run_store.list_execution_audit(
        run_id=request.run_id,
        execution_id=execution_id,
        audit_ids=request.audit_ids or None,
    )
    if not audit_records:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No audit records found for execution '{execution_id}'.",
        )

    rollback_result = rollback_service.rollback(
        request=request,
        audit_records=audit_records,
        execution_id=execution_id,
    )

    if not request.dry_run:
        status_map = {
            RollbackActionStatus.ROLLED_BACK: RollbackStatus.ROLLED_BACK,
            RollbackActionStatus.FAILED: RollbackStatus.FAILED,
        }
        for item in rollback_result.results:
            mapped = status_map.get(item.status)
            if mapped:
                run_store.update_rollback_status(
                    audit_id=item.audit_id,
                    rollback_status=mapped,
                    message=item.message,
                )

    return rollback_result


@router.get("/runs", response_model=list[RunSummary])
def list_runs() -> list[RunSummary]:
    records = run_store.list()
    response: list[RunSummary] = []

    for record in records:
        estimated_savings = (
            record.savings_summary.total_monthly_savings
            if record.savings_summary is not None
            else sum(recommendation.estimated_monthly_savings for recommendation in record.recommendations)
        )

        response.append(
            RunSummary(
                run_id=record.run_id,
                status=record.status,
                recommendation_count=len(record.recommendations),
                estimated_monthly_savings=estimated_savings,
                updated_at=record.updated_at,
            )
        )

    return response


@router.get("/runs/{run_id}", response_model=RunDetails)
def get_run(run_id: str) -> RunDetails:
    record = run_store.get(run_id)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Run '{run_id}' was not found.",
        )

    audit_records = run_store.list_execution_audit(run_id=run_id)

    return RunDetails(
        run_id=record.run_id,
        status=record.status,
        recommendations=record.recommendations,
        scores=record.scores,
        savings_details=record.savings_details,
        savings_summary=record.savings_summary,
        execution=record.execution,
        audit_records=audit_records,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


@router.get("/runs/{run_id}/audit", response_model=list[ExecutionAuditRecord])
def get_run_audit(
    run_id: str,
    execution_id: str | None = Query(default=None),
) -> list[ExecutionAuditRecord]:
    record = run_store.get(run_id)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Run '{run_id}' was not found.",
        )

    return run_store.list_execution_audit(run_id=run_id, execution_id=execution_id)
