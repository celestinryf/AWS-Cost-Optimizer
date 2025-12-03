# executor/state_tracker.py
"""
State tracking for execution audit trail and rollback support.

Tracks:
- Pre-execution state snapshots
- Executed actions
- Success/failure status
- Rollback information
"""

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional
import uuid


class ExecutionStatus(Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"
    PARTIALLY_COMPLETED = "partially_completed"


@dataclass
class StateSnapshot:
    """Snapshot of object state before modification."""
    
    bucket: str
    key: Optional[str]
    storage_class: Optional[str] = None
    size_bytes: int = 0
    etag: Optional[str] = None
    last_modified: Optional[str] = None
    version_id: Optional[str] = None
    tags: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)
    
    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ExecutionRecord:
    """Record of a single executed action."""
    
    id: str
    recommendation_id: str
    action_type: str
    
    # Target
    bucket: str
    key: Optional[str]
    
    # State
    status: ExecutionStatus
    pre_state: Optional[StateSnapshot]
    post_state: Optional[dict] = None
    
    # Timing
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    
    # Results
    success: bool = False
    error_message: Optional[str] = None
    
    # Rollback info
    rollback_available: bool = False
    rollback_action: Optional[str] = None
    rolled_back_at: Optional[datetime] = None
    
    def to_dict(self) -> dict:
        data = {
            "id": self.id,
            "recommendation_id": self.recommendation_id,
            "action_type": self.action_type,
            "bucket": self.bucket,
            "key": self.key,
            "status": self.status.value,
            "pre_state": self.pre_state.to_dict() if self.pre_state else None,
            "post_state": self.post_state,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "success": self.success,
            "error_message": self.error_message,
            "rollback_available": self.rollback_available,
            "rollback_action": self.rollback_action,
            "rolled_back_at": self.rolled_back_at.isoformat() if self.rolled_back_at else None,
        }
        return data


@dataclass
class ExecutionBatch:
    """A batch of executions run together."""
    
    id: str
    started_at: datetime
    completed_at: Optional[datetime] = None
    
    status: ExecutionStatus = ExecutionStatus.PENDING
    
    total_actions: int = 0
    successful: int = 0
    failed: int = 0
    skipped: int = 0
    
    records: list[ExecutionRecord] = field(default_factory=list)
    
    # Settings used
    dry_run: bool = False
    skip_high_risk: bool = True
    require_approval: bool = True
    
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "status": self.status.value,
            "total_actions": self.total_actions,
            "successful": self.successful,
            "failed": self.failed,
            "skipped": self.skipped,
            "records": [r.to_dict() for r in self.records],
            "dry_run": self.dry_run,
            "skip_high_risk": self.skip_high_risk,
            "require_approval": self.require_approval,
        }


class StateTracker:
    """
    Tracks execution state for audit and rollback.
    
    Persists state to disk so recovery is possible after crashes.
    """
    
    def __init__(self, state_dir: str = "reports/execution_state"):
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        
        self.current_batch: Optional[ExecutionBatch] = None
        self.records: dict[str, ExecutionRecord] = {}
    
    def start_batch(
        self, 
        total_actions: int,
        dry_run: bool = False,
        skip_high_risk: bool = True,
        require_approval: bool = True
    ) -> ExecutionBatch:
        """Start a new execution batch."""
        batch = ExecutionBatch(
            id=str(uuid.uuid4()),
            started_at=datetime.now(timezone.utc),
            status=ExecutionStatus.IN_PROGRESS,
            total_actions=total_actions,
            dry_run=dry_run,
            skip_high_risk=skip_high_risk,
            require_approval=require_approval,
        )
        
        self.current_batch = batch
        self._save_batch(batch)
        
        return batch
    
    def record_start(
        self,
        recommendation_id: str,
        action_type: str,
        bucket: str,
        key: Optional[str],
        pre_state: Optional[StateSnapshot],
        rollback_available: bool = False,
        rollback_action: Optional[str] = None,
    ) -> ExecutionRecord:
        """Record the start of an action."""
        record = ExecutionRecord(
            id=str(uuid.uuid4()),
            recommendation_id=recommendation_id,
            action_type=action_type,
            bucket=bucket,
            key=key,
            status=ExecutionStatus.IN_PROGRESS,
            pre_state=pre_state,
            started_at=datetime.now(timezone.utc),
            rollback_available=rollback_available,
            rollback_action=rollback_action,
        )
        
        self.records[record.id] = record
        
        if self.current_batch:
            self.current_batch.records.append(record)
            self._save_batch(self.current_batch)
        
        return record
    
    def record_success(
        self,
        record_id: str,
        post_state: Optional[dict] = None
    ) -> None:
        """Record successful completion of an action."""
        if record_id not in self.records:
            return
        
        record = self.records[record_id]
        record.status = ExecutionStatus.COMPLETED
        record.success = True
        record.completed_at = datetime.now(timezone.utc)
        record.post_state = post_state
        
        if self.current_batch:
            self.current_batch.successful += 1
            self._save_batch(self.current_batch)
    
    def record_failure(
        self,
        record_id: str,
        error_message: str
    ) -> None:
        """Record failed action."""
        if record_id not in self.records:
            return
        
        record = self.records[record_id]
        record.status = ExecutionStatus.FAILED
        record.success = False
        record.completed_at = datetime.now(timezone.utc)
        record.error_message = error_message
        
        if self.current_batch:
            self.current_batch.failed += 1
            self._save_batch(self.current_batch)
    
    def record_skip(
        self,
        recommendation_id: str,
        action_type: str,
        bucket: str,
        key: Optional[str],
        reason: str
    ) -> ExecutionRecord:
        """Record a skipped action."""
        record = ExecutionRecord(
            id=str(uuid.uuid4()),
            recommendation_id=recommendation_id,
            action_type=action_type,
            bucket=bucket,
            key=key,
            status=ExecutionStatus.COMPLETED,
            pre_state=None,
            started_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
            success=True,
            error_message=f"Skipped: {reason}",
        )
        
        self.records[record.id] = record
        
        if self.current_batch:
            self.current_batch.skipped += 1
            self.current_batch.records.append(record)
            self._save_batch(self.current_batch)
        
        return record
    
    def record_rollback(self, record_id: str) -> None:
        """Record that an action was rolled back."""
        if record_id not in self.records:
            return
        
        record = self.records[record_id]
        record.status = ExecutionStatus.ROLLED_BACK
        record.rolled_back_at = datetime.now(timezone.utc)
        
        if self.current_batch:
            self._save_batch(self.current_batch)
    
    def complete_batch(self, status: Optional[ExecutionStatus] = None) -> None:
        """Mark the current batch as complete."""
        if not self.current_batch:
            return
        
        self.current_batch.completed_at = datetime.now(timezone.utc)
        
        if status:
            self.current_batch.status = status
        elif self.current_batch.failed > 0:
            self.current_batch.status = ExecutionStatus.PARTIALLY_COMPLETED
        else:
            self.current_batch.status = ExecutionStatus.COMPLETED
        
        self._save_batch(self.current_batch)
    
    def get_rollback_candidates(self) -> list[ExecutionRecord]:
        """Get all records that can be rolled back."""
        return [
            r for r in self.records.values()
            if r.rollback_available 
            and r.success 
            and r.status != ExecutionStatus.ROLLED_BACK
        ]
    
    def _save_batch(self, batch: ExecutionBatch) -> None:
        """Persist batch state to disk."""
        filepath = self.state_dir / f"batch_{batch.id}.json"
        with open(filepath, "w") as f:
            json.dump(batch.to_dict(), f, indent=2)
    
    def load_batch(self, batch_id: str) -> Optional[ExecutionBatch]:
        """Load a batch from disk."""
        filepath = self.state_dir / f"batch_{batch_id}.json"
        if not filepath.exists():
            return None
        
        with open(filepath) as f:
            data = json.load(f)
        
        # Reconstruct batch
        batch = ExecutionBatch(
            id=data["id"],
            started_at=datetime.fromisoformat(data["started_at"]),
            completed_at=datetime.fromisoformat(data["completed_at"]) if data.get("completed_at") else None,
            status=ExecutionStatus(data["status"]),
            total_actions=data["total_actions"],
            successful=data["successful"],
            failed=data["failed"],
            skipped=data["skipped"],
            dry_run=data.get("dry_run", False),
            skip_high_risk=data.get("skip_high_risk", True),
            require_approval=data.get("require_approval", True),
        )
        
        # Reconstruct records
        for r in data.get("records", []):
            pre_state = None
            if r.get("pre_state"):
                pre_state = StateSnapshot(**r["pre_state"])
            
            record = ExecutionRecord(
                id=r["id"],
                recommendation_id=r["recommendation_id"],
                action_type=r["action_type"],
                bucket=r["bucket"],
                key=r.get("key"),
                status=ExecutionStatus(r["status"]),
                pre_state=pre_state,
                post_state=r.get("post_state"),
                started_at=datetime.fromisoformat(r["started_at"]) if r.get("started_at") else None,
                completed_at=datetime.fromisoformat(r["completed_at"]) if r.get("completed_at") else None,
                success=r.get("success", False),
                error_message=r.get("error_message"),
                rollback_available=r.get("rollback_available", False),
                rollback_action=r.get("rollback_action"),
                rolled_back_at=datetime.fromisoformat(r["rolled_back_at"]) if r.get("rolled_back_at") else None,
            )
            
            batch.records.append(record)
            self.records[record.id] = record
        
        return batch
    
    def get_recent_batches(self, limit: int = 10) -> list[dict]:
        """Get recent execution batches."""
        batches = []
        
        for filepath in sorted(self.state_dir.glob("batch_*.json"), reverse=True)[:limit]:
            with open(filepath) as f:
                data = json.load(f)
                batches.append({
                    "id": data["id"],
                    "started_at": data["started_at"],
                    "status": data["status"],
                    "total": data["total_actions"],
                    "successful": data["successful"],
                    "failed": data["failed"],
                })
        
        return batches