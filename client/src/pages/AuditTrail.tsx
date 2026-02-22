import { useEffect, useState, useCallback } from "react";
import { useParams, Link } from "react-router-dom";
import { api, ApiError } from "../api/client";
import type { ExecutionAuditRecord, RollbackRequest } from "../types";
import StatusBadge from "../components/StatusBadge";
import RiskBadge from "../components/RiskBadge";
import styles from "./AuditTrail.module.css";

function fmtDate(iso: string) {
  return new Date(iso).toLocaleString();
}

export default function AuditTrail() {
  const { runId } = useParams<{ runId: string }>();
  const [records, setRecords] = useState<ExecutionAuditRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [rbDryRun, setRbDryRun] = useState(true);
  const [rollingBack, setRollingBack] = useState(false);
  const [rbResult, setRbResult] = useState<string | null>(null);

  const loadAudit = useCallback(async () => {
    if (!runId) return;
    try {
      const data = await api.getAudit(runId);
      setRecords(data);
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to load audit records");
    } finally {
      setLoading(false);
    }
  }, [runId]);

  useEffect(() => { void loadAudit(); }, [loadAudit]);

  function toggleExpand(id: string) {
    setExpanded((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  }

  function toggleSelect(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  }

  function toggleAll(checked: boolean) {
    setSelected(checked ? new Set(rollbackEligible.map((r) => r.audit_id)) : new Set());
  }

  const rollbackEligible = records.filter((r) => r.rollback_available);

  async function handleRollbackSelected() {
    if (!runId || selected.size === 0) return;
    setRollingBack(true);
    setRbResult(null);
    try {
      const req: RollbackRequest = {
        run_id: runId,
        execution_id: records[0]?.execution_id ?? null,
        dry_run: rbDryRun,
        audit_ids: Array.from(selected),
      };
      const resp = await api.rollback(req);
      setRbResult(
        `${rbDryRun ? "[Dry Run] " : ""}Rolled back: ${resp.rolled_back}, Skipped: ${resp.skipped}, Failed: ${resp.failed}`,
      );
      if (!rbDryRun) {
        setSelected(new Set());
        await loadAudit();
      }
    } catch (e) {
      setRbResult(`Error: ${e instanceof ApiError ? e.message : "Rollback failed"}`);
    } finally {
      setRollingBack(false);
    }
  }

  if (loading) return <div className={styles.centered}>Loading…</div>;

  return (
    <div className={styles.page}>
      <div className={styles.breadcrumb}>
        <Link to="/">Runs</Link>
        {" / "}
        <Link to={`/runs/${runId}`} className="mono">{runId?.slice(0, 8)}…</Link>
        {" / Audit Trail"}
      </div>

      <h1 className={styles.heading}>Audit Trail</h1>

      {error && <div className={styles.error}>{error}</div>}

      {/* Rollback toolbar */}
      {rollbackEligible.length > 0 && (
        <div className={styles.toolbar}>
          <label className={styles.toggle}>
            <input
              type="checkbox"
              onChange={(e) => toggleAll(e.target.checked)}
              checked={selected.size === rollbackEligible.length && rollbackEligible.length > 0}
            />
            Select all eligible ({rollbackEligible.length})
          </label>
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
            disabled={selected.size === 0 || rollingBack}
            onClick={handleRollbackSelected}
          >
            {rollingBack
              ? "Rolling back…"
              : `Rollback Selected (${selected.size})`}
          </button>
          {rbResult && <span className={styles.rbResult}>{rbResult}</span>}
        </div>
      )}

      <div className={styles.tableWrap}>
        <table>
          <thead>
            <tr>
              <th style={{ width: 36 }}></th>
              <th>Type</th>
              <th>Bucket / Key</th>
              <th>Risk</th>
              <th>Action Status</th>
              <th>Rollback</th>
              <th>Timestamp</th>
              <th style={{ width: 36 }}></th>
            </tr>
          </thead>
          <tbody>
            {records.map((rec) => (
              <>
                <tr key={rec.audit_id} className={styles.row}>
                  <td>
                    {rec.rollback_available && (
                      <input
                        type="checkbox"
                        checked={selected.has(rec.audit_id)}
                        onChange={() => toggleSelect(rec.audit_id)}
                      />
                    )}
                  </td>
                  <td>
                    <span className={styles.typeChip}>
                      {rec.recommendation_type.replace(/_/g, " ")}
                    </span>
                  </td>
                  <td className="mono truncate" style={{ maxWidth: 220 }}>
                    {rec.bucket}{rec.key ? `/${rec.key}` : ""}
                  </td>
                  <td><RiskBadge level={rec.risk_level} /></td>
                  <td><StatusBadge status={rec.action_status} /></td>
                  <td><StatusBadge status={rec.rollback_status} /></td>
                  <td className="text-muted">{fmtDate(rec.created_at)}</td>
                  <td>
                    <button
                      className={styles.expandBtn}
                      onClick={() => toggleExpand(rec.audit_id)}
                    >
                      {expanded.has(rec.audit_id) ? "▲" : "▼"}
                    </button>
                  </td>
                </tr>
                {expanded.has(rec.audit_id) && (
                  <tr key={`${rec.audit_id}-detail`} className={styles.detailRow}>
                    <td colSpan={8}>
                      <div className={styles.detail}>
                        <div className={styles.detailCol}>
                          <div className={styles.detailLabel}>Pre-change state</div>
                          <pre className={styles.json}>
                            {JSON.stringify(rec.pre_change_state, null, 2)}
                          </pre>
                        </div>
                        {rec.post_change_state && (
                          <div className={styles.detailCol}>
                            <div className={styles.detailLabel}>Post-change state</div>
                            <pre className={styles.json}>
                              {JSON.stringify(rec.post_change_state, null, 2)}
                            </pre>
                          </div>
                        )}
                        <div className={styles.detailCol}>
                          <div className={styles.detailLabel}>Message</div>
                          <p className={styles.message}>{rec.message}</p>
                          {rec.missing_permissions.length > 0 && (
                            <>
                              <div className={styles.detailLabel} style={{ marginTop: 8 }}>
                                Missing permissions
                              </div>
                              <ul className={styles.permList}>
                                {rec.missing_permissions.map((p) => (
                                  <li key={p} className="mono">{p}</li>
                                ))}
                              </ul>
                            </>
                          )}
                        </div>
                      </div>
                    </td>
                  </tr>
                )}
              </>
            ))}
          </tbody>
        </table>

        {records.length === 0 && (
          <div className={styles.empty}>No audit records yet. Execute a run first.</div>
        )}
      </div>
    </div>
  );
}
