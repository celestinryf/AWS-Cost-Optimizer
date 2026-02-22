import { Routes, Route, Navigate } from "react-router-dom";
import Dashboard from "./pages/Dashboard";
import RunDetail from "./pages/RunDetail";
import AuditTrail from "./pages/AuditTrail";
import styles from "./App.module.css";

export default function App() {
  return (
    <div className={styles.shell}>
      <header className={styles.header}>
        <span className={styles.logo}>AWS Cost Optimizer</span>
      </header>
      <main className={styles.main}>
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/runs/:runId" element={<RunDetail />} />
          <Route path="/runs/:runId/audit" element={<AuditTrail />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  );
}
