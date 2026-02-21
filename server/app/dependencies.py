import os

from app.executor import ExecutionService, RollbackService
from app.scanner import ScannerService
from app.scoring import ScoringService
from app.state import RunStore


run_store = RunStore(db_path=os.getenv("RUNS_DB_PATH", "data/runs.db"))
scanner_service = ScannerService()
scoring_service = ScoringService()
execution_service = ExecutionService()
rollback_service = RollbackService()
