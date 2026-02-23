import os

import boto3

from app.executor import ExecutionService, RollbackService
from app.scanner import ScannerService
from app.scoring import ScoringService
from app.state import RunStore

_s3 = boto3.client("s3", region_name=os.getenv("AWS_DEFAULT_REGION"))

run_store = RunStore(db_path=os.getenv("RUNS_DB_PATH", "data/runs.db"))
scanner_service = ScannerService(s3_client=_s3)
scoring_service = ScoringService()
execution_service = ExecutionService(s3_client=_s3)
rollback_service = RollbackService(s3_client=_s3)
