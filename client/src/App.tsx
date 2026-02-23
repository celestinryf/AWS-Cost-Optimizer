import { useEffect } from "react";
import { Routes, Route, Navigate, Link, useNavigate } from "react-router-dom";
import { invoke } from "@tauri-apps/api/core";
import Dashboard from "./pages/Dashboard";
import RunDetail from "./pages/RunDetail";
import AuditTrail from "./pages/AuditTrail";
import Settings from "./pages/Settings";
import styles from "./App.module.css";

const IS_TAURI = typeof window !== "undefined" && "__TAURI__" in window;

function AppShell() {
  const navigate = useNavigate();

  // On first load in production: if no credentials are stored, redirect to
  // settings so the user can configure AWS access before scanning.
  useEffect(() => {
    if (!IS_TAURI || import.meta.env.DEV) return;
    invoke<unknown>("load_credentials").then((creds) => {
      if (!creds) navigate("/settings", { replace: true });
    });
  }, [navigate]);

  return (
    <div className={styles.shell}>
      <header className={styles.header}>
        <Link to="/" className={styles.logo}>
          AWS Cost Optimizer
        </Link>
        <nav className={styles.nav}>
          <Link to="/settings" className={styles.navLink}>
            Settings
          </Link>
        </nav>
      </header>
      <main className={styles.main}>
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/runs/:runId" element={<RunDetail />} />
          <Route path="/runs/:runId/audit" element={<AuditTrail />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  );
}

export default function App() {
  return <AppShell />;
}
