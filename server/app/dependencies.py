from app.executor import ExecutionService
from app.scanner import ScannerService
from app.scoring import ScoringService
from app.state import RunStore


run_store = RunStore()
scanner_service = ScannerService()
scoring_service = ScoringService()
execution_service = ExecutionService()

