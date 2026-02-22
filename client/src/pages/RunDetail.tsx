import { useEffect, useState, useCallback } from "react";
import { useParams, Link } from "react-router-dom";
import { api, ApiError } from "../api/client";
import type { ExecutionMode, RunDetails } from "../types";
import StatusBadge from "../components/StatusBadge";
import RiskBadge from "../components/RiskBadge";
import styles from "./RunDetail.module.css";

function fmt(n: number) {
  return `$${n.toFixed(2)}`;
}

export default function RunDetail() {
  const { runId } = useParams<{ runId: string }>();
  const [run, setRun] = useState<RunDetails | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Action states
  const [scoring, setScoring] = useState(false);
  const [executing, setExecuting] = useState(false);
  const [rollingBack, setRollingBack] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  // Execute config
  const [mode, setMode] = useState<ExecutionMode>("dry_run");
  const [dryRun, setDryRun] = useState(true);
  const [maxActions, setMaxActions] = useState(100);
  const [rbDryRun, setRbDryRun] = useState(true);

  const loadRun = useCallback(async () => {
    if (!runId) return;
    try {
      const data = await api.getRun(runId);
      setRun(data);
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to load run");
    } finally {
      setLoading(false);
    }
  }, [runId]);

  useEffect(() => { void loadRun(); }, [loadRun]);

  async function handleScore() {
    if (!runId) return;
    setScoring(true);
    setActionError(null);
    try {
      await api.score({ run_id: runId });
      await loadRun();
    } catch (e) {
      setActionError(e instanceof ApiError ? e.message : "Score failed");
    } finally {
      setScoring(false);
    }
  }

  async function handleExecute() {
    if (!runId) return;
    setExecuting(true);
    setActionError(null);
    try {
      await api.execute({ run_id: runId, mode, dry_run: dryRun, max_actions: maxActions });
      await loadRun();
    } catch (e) {
      setActionError(e instanceof ApiError ? e.message : "Execute failed");
    } finally {
      setExecuting(false);
    }
  }

  async function handleRollback() {
    if (!runId) return;
    setRollingBack(true);
    setActionError(null);
    try {
      await api.rollback({
        run_id: runId,
        execution_id: run?.execution?.execution_id ?? null,
        dry_run: rbDryRun,
        audit_ids: [],
      });
      await loadRun();
    } catch (e) {
      setActionError(e instanceof ApiError ? e.message : "Rollback failed");
    } finally {
      setRollingBack(false);
    }
  }

  if (loading) return <div className={styles.centered}>Loading…</div>;
  if (error || !run) return <div className={styles.centered + " " + styles.err}>{error ?? "Run not found"}</div>;

  const scored = run.status === "scored" || run.status === "executed";
  const hasExecution = !!run.execution;

  return (
    <div className={styles.page}>
      {/* Header */}
      <div className={styles.header}>
        <Link to="/" className={styles.back}>← Runs</Link>
        <div className={styles.headerRow}>
          <div>
            <h1 className={styles.runId + " mono"}>{run.run_id}</h1>
            <div className={styles.meta}>
              <StatusBadge status={run.status} />
              {run.savings_summary && (
                <span className={styles.savings}>
                  {fmt(run.savings_summary.total_monthly_savings)}/mo potential savings
                </span>
              )}
              <Link to={`/runs/${run.run_id}/audit`} className={styles.auditLink}>
                View audit trail →
              </Link>
            </div>
          </div>
        </div>
      </div>

      <div className={styles.body}>
        {/* Recommendations table */}
        <div className={styles.main}>
          <h2 className={styles.sectionTitle}>
            Recommendations ({run.recommendations.length})
          </h2>
          <div className={styles.tableWrap}>
            <table>
              <thead>
                <tr>
                  <th>Type</th>
                  <th>Bucket / Key</th>
                  <th>Risk</th>
                  <th>Savings/mo</th>
                  <th>Reason</th>
                </tr>
              </thead>
              <tbody>
                {run.recommendations.map((rec) => (
                  <tr key={rec.id}>
                    <td>
                      <span className={styles.typeChip}>
                        {rec.recommendation_type.replace(/_/g, " ")}
                      </span>
                    </td>
                    <td>
                      <div className="mono truncate" style={{ maxWidth: 260 }}>
                        {rec.bucket}{rec.key ? `/${rec.key}` : ""}
                      </div>
                    </td>
                    <td><RiskBadge level={rec.risk_level} /></td>
                    <td className={styles.savings}>{fmt(rec.estimated_monthly_savings)}</td>
                    <td className="text-muted">{rec.reason}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Execution summary */}
          {run.execution && (
            <div className={styles.execSummary}>
              <h2 className={styles.sectionTitle}>Execution Results</h2>
              <div className={styles.counts}>
                {[
                  { label: "Eligible", val: run.execution.eligible },
                  { label: "Executed", val: run.execution.executed, highlight: true },
                  { label: "Skipped",  val: run.execution.skipped },
                  { label: "Blocked",  val: run.execution.blocked },
                  { label: "Failed",   val: run.execution.failed },
                ].map(({ label, val, highlight }) => (
                  <div key={label} className={`${styles.countCard} ${highlight ? styles.highlight : ""}`}>
                    <div className={styles.countVal}>{val}</div>
                    <div className={styles.countLabel}>{label}</div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Action panel */}
        <aside className={styles.panel}>
          {actionError && <div className={styles.panelError}>{actionError}</div>}

          {/* Score */}
          <section className={styles.panelSection}>
            <h3 className={styles.panelTitle}>1. Score</h3>
            <p className={styles.panelDesc}>
              Analyze risk and estimate savings for each recommendation.
            </p>
            <button
              className="btn-primary"
              style={{ width: "100%" }}
              onClick={handleScore}
              disabled={scoring || scored}
            >
              {scoring ? "Scoring…" : scored ? "Already Scored" : "Score Recommendations"}
            </button>
          </section>

          {/* Execute */}
          <section className={styles.panelSection}>
            <h3 className={styles.panelTitle}>2. Execute</h3>
            <label className={styles.fieldLabel}>
              Mode
              <select
                value={mode}
                onChange={(e) => setMode(e.target.value as ExecutionMode)}
                disabled={!scored}
              >
                <option value="dry_run">Dry Run</option>
                <option value="safe">Safe</option>
                <option value="standard">Standard</option>
                <option value="full">Full</option>
              </select>
            </label>
            <label className={styles.fieldLabel}>
              Max actions
              <input
                type="number"
                min={1}
                max={10000}
                value={maxActions}
                onChange={(e) => setMaxActions(Number(e.target.value))}
                disabled={!scored}
              />
            </label>
            <label className={styles.toggle}>
              <input
                type="checkbox"
                checked={dryRun}
                onChange={(e) => setDryRun(e.target.checked)}
                disabled={!scored || mode === "dry_run"}
              />
              Dry run
            </label>
            <button
              className="btn-primary"
              style={{ width: "100%" }}
              onClick={handleExecute}
              disabled={!scored || executing}
            >
              {executing ? "Executing…" : "Execute"}
            </button>
          </section>

          {/* Rollback */}
          {hasExecution && (
            <section className={styles.panelSection}>
              <h3 className={styles.panelTitle}>3. Rollback</h3>
              <p className={styles.panelDesc}>
                Reverse eligible executed actions. For selective rollback, use the{" "}
                <Link to={`/runs/${run.run_id}/audit`}>audit trail</Link>.
              </p>
              <label className={styles.toggle}>
                <input
                  type="checkbox"
                  checked={rbDryRun}
                  onChange={(e) => setRbDryRun(e.target.checked)}
                />
                Dry run
              </label>
              <button
                className="btn-danger"
                style={{ width: "100%" }}
                onClick={handleRollback}
                disabled={rollingBack}
              >
                {rollingBack ? "Rolling back…" : "Rollback All"}
              </button>
            </section>
          )}
        </aside>
      </div>
    </div>
  );
}
