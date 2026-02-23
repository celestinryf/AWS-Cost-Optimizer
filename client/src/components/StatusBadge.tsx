import type { ExecutionActionStatus, RollbackStatus, RunStatus } from "../types";
import styles from "./StatusBadge.module.css";

type AnyStatus = RunStatus | ExecutionActionStatus | RollbackStatus | string;

const STATUS_META: Record<string, { label: string; cls: string }> = {
  // RunStatus
  scanned:        { label: "Scanned",  cls: "info" },
  scored:         { label: "Scored",   cls: "info" },
  executed:       { label: "Executed", cls: "success" },
  // ExecutionActionStatus
  executed_action: { label: "Executed", cls: "success" },
  dry_run:        { label: "Dry Run",  cls: "neutral" },
  skipped:        { label: "Skipped",  cls: "neutral" },
  blocked:        { label: "Blocked",  cls: "warning" },
  failed:         { label: "Failed",   cls: "danger" },
  // RollbackStatus
  pending:        { label: "Pending",       cls: "info" },
  rolled_back:    { label: "Rolled Back",   cls: "success" },
  not_applicable: { label: "N/A",           cls: "neutral" },
};

interface Props {
  status: AnyStatus;
}

export default function StatusBadge({ status }: Props) {
  const meta = STATUS_META[status] ?? { label: status, cls: "neutral" };
  return (
    <span className={`${styles.badge} ${styles[meta.cls]}`}>
      {meta.label}
    </span>
  );
}
