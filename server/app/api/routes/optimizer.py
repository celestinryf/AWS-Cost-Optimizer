from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, status

from app.dependencies import execution_service, run_store, scanner_service, scoring_service
from app.models import (
    ExecuteRequest,
    ExecuteResponse,
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

    scores = scoring_service.score(record.recommendations)
    updated = run_store.set_scores(request.run_id, scores)
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Run '{request.run_id}' was not found.",
        )

    safe_to_automate = len([item for item in scores if item.safe_to_automate])
    requires_approval = len([item for item in scores if item.requires_approval])

    return ScoreResponse(
        run_id=updated.run_id,
        status=updated.status,
        scores=scores,
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


@router.get("/runs", response_model=list[RunSummary])
def list_runs() -> list[RunSummary]:
    records = run_store.list()
    response: list[RunSummary] = []

    for record in records:
        response.append(
            RunSummary(
                run_id=record.run_id,
                status=record.status,
                recommendation_count=len(record.recommendations),
                estimated_monthly_savings=sum(
                    recommendation.estimated_monthly_savings
                    for recommendation in record.recommendations
                ),
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

    return RunDetails(
        run_id=record.run_id,
        status=record.status,
        recommendations=record.recommendations,
        scores=record.scores,
        execution=record.execution,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )

