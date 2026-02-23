import { useEffect, useState, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { api, ApiError } from "../api/client";
import type { RunSummary, ScanRequest } from "../types";
import StatusBadge from "../components/StatusBadge";
import ScanModal from "../components/ScanModal";
import styles from "./Dashboard.module.css";

function fmt(n: number) {
  return `$${n.toFixed(2)}`;
}

function fmtDate(iso: string) {
  return new Date(iso).toLocaleString();
}

export default function Dashboard() {
  const navigate = useNavigate();
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showScan, setShowScan] = useState(false);
  const [scanning, setScanning] = useState(false);

  const loadRuns = useCallback(async () => {
    try {
      const data = await api.listRuns();
      setRuns(data);
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to connect to backend");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadRuns();
    const timer = setInterval(() => void loadRuns(), 30_000);
    return () => clearInterval(timer);
  }, [loadRuns]);

  async function handleScan(req: ScanRequest) {
    setScanning(true);
    try {
      const resp = await api.scan(req);
      setShowScan(false);
      await loadRuns();
      navigate(`/runs/${resp.run_id}`);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Scan failed");
    } finally {
      setScanning(false);
    }
  }

  return (
    <div className={styles.page}>
      <div className={styles.toolbar}>
        <h1 className={styles.heading}>Runs</h1>
        <button className="btn-primary" onClick={() => setShowScan(true)}>
          + New Scan
        </button>
      </div>

      {error && <div className={styles.error}>{error}</div>}

      {loading ? (
        <div className={styles.empty}>Loading…</div>
      ) : runs.length === 0 ? (
        <div className={styles.empty}>
          No runs yet.{" "}
          <button className="btn-secondary" onClick={() => setShowScan(true)}>
            Start your first scan
          </button>
        </div>
      ) : (
        <div className={styles.tableWrap}>
          <table>
            <thead>
              <tr>
                <th>Status</th>
                <th>Run ID</th>
                <th>Recommendations</th>
                <th>Est. Monthly Savings</th>
                <th>Updated</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((run) => (
                <tr
                  key={run.run_id}
                  className={styles.row}
                  onClick={() => navigate(`/runs/${run.run_id}`)}
                >
                  <td><StatusBadge status={run.status} /></td>
                  <td className="mono">{run.run_id.slice(0, 8)}…</td>
                  <td>{run.recommendation_count}</td>
                  <td className={styles.savings}>{fmt(run.estimated_monthly_savings)}/mo</td>
                  <td className="text-muted">{fmtDate(run.updated_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {showScan && (
        <ScanModal
          onConfirm={handleScan}
          onClose={() => setShowScan(false)}
          loading={scanning}
        />
      )}
    </div>
  );
}
