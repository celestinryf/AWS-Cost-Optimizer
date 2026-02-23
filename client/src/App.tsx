import { useEffect, useState, useCallback } from "react";
import { Routes, Route, Navigate, Link, useNavigate } from "react-router-dom";
import { invoke } from "@tauri-apps/api/core";
import { api } from "./api/client";
import Dashboard from "./pages/Dashboard";
import RunDetail from "./pages/RunDetail";
import AuditTrail from "./pages/AuditTrail";
import Settings from "./pages/Settings";
import styles from "./App.module.css";

// Check for updates a few seconds after launch so it never slows down startup.
const UPDATE_CHECK_DELAY_MS = 5_000;

const IS_TAURI = typeof window !== "undefined" && "__TAURI__" in window;

function AppShell() {
  const navigate = useNavigate();
  // null = first check still pending, true = online, false = offline
  const [backendOnline, setBackendOnline] = useState<boolean | null>(null);
  // null = not checked yet, string = new version available, false = up to date
  const [updateVersion, setUpdateVersion] = useState<string | null | false>(null);
  const [installing, setInstalling] = useState(false);

  const checkHealth = useCallback(async () => {
    try {
      await api.health();
      setBackendOnline(true);
    } catch {
      setBackendOnline(false);
    }
  }, []);

  // Initial check on mount + poll every 10 s to catch crashes or recovery.
  useEffect(() => {
    void checkHealth();
    const timer = setInterval(() => void checkHealth(), 10_000);
    return () => clearInterval(timer);
  }, [checkHealth]);

  // Check for a new release once, a few seconds after launch.
  useEffect(() => {
    if (!IS_TAURI || import.meta.env.DEV) return;
    const timer = setTimeout(async () => {
      try {
        const version = await invoke<string | null>("check_for_updates");
        setUpdateVersion(version ?? false);
      } catch {
        // Updater not configured (missing pubkey, no network, etc.) — silently ignore.
        setUpdateVersion(false);
      }
    }, UPDATE_CHECK_DELAY_MS);
    return () => clearTimeout(timer);
  }, []);

  async function handleInstallUpdate() {
    setInstalling(true);
    try {
      await invoke("install_update");
      // Tauri restarts the app automatically after installing.
    } catch (e) {
      console.error("Update install failed:", e);
      setInstalling(false);
    }
  }

  // First-run redirect: in production, send users without stored credentials
  // to /settings before they can attempt a scan.
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
          {backendOnline === false && (
            <span className={styles.offlinePill}>Backend offline</span>
          )}
          <Link to="/settings" className={styles.navLink}>
            Settings
          </Link>
        </nav>
      </header>

      {backendOnline === false && (
        <div className={styles.offlineBanner}>
          Backend is unreachable. Check your AWS credentials in{" "}
          <Link to="/settings">Settings</Link> or restart the app.{" "}
          <button className={styles.retryBtn} onClick={() => void checkHealth()}>
            Retry now
          </button>
        </div>
      )}

      {typeof updateVersion === "string" && (
        <div className={styles.updateBanner}>
          Update available — v{updateVersion} is ready to install.{" "}
          <button
            className={styles.updateBtn}
            disabled={installing}
            onClick={() => void handleInstallUpdate()}
          >
            {installing ? "Installing…" : "Install & Restart"}
          </button>
        </div>
      )}

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
