import { useState, useEffect } from "react";
import { invoke } from "@tauri-apps/api/core";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import styles from "./Settings.module.css";

interface AwsCredentials {
  access_key_id: string;
  secret_access_key: string;
  region: string;
  session_token?: string | null;
}

const REGIONS = [
  "us-east-1",
  "us-east-2",
  "us-west-1",
  "us-west-2",
  "eu-west-1",
  "eu-west-2",
  "eu-west-3",
  "eu-central-1",
  "eu-north-1",
  "ap-south-1",
  "ap-northeast-1",
  "ap-northeast-2",
  "ap-northeast-3",
  "ap-southeast-1",
  "ap-southeast-2",
  "sa-east-1",
  "ca-central-1",
  "me-south-1",
  "af-south-1",
];

const IS_TAURI = typeof window !== "undefined" && "__TAURI__" in window;

export default function Settings() {
  const navigate = useNavigate();
  const [form, setForm] = useState<AwsCredentials>({
    access_key_id: "",
    secret_access_key: "",
    region: "us-east-1",
    session_token: "",
  });
  const [showSecret, setShowSecret] = useState(false);
  const [showToken, setShowToken] = useState(false);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [saved, setSaved] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<{ ok: boolean; message: string } | null>(null);

  // Pre-populate form with any already-stored credentials.
  useEffect(() => {
    if (!IS_TAURI) return;
    invoke<AwsCredentials | null>("load_credentials").then((creds) => {
      if (creds) {
        setForm({
          access_key_id: creds.access_key_id,
          secret_access_key: creds.secret_access_key,
          region: creds.region,
          session_token: creds.session_token ?? "",
        });
      }
    });
  }, []);

  const setField = (key: keyof AwsCredentials, value: string) => {
    setForm((prev) => ({ ...prev, [key]: value }));
    setSaved(false);
    setSaveError(null);
  };

  const handleSave = async () => {
    if (!form.access_key_id.trim() || !form.secret_access_key.trim() || !form.region) {
      setSaveError("Access Key ID, Secret Access Key, and Region are required.");
      return;
    }
    setSaving(true);
    setSaved(false);
    setSaveError(null);
    try {
      if (IS_TAURI) {
        await invoke("save_credentials", {
          creds: {
            access_key_id: form.access_key_id.trim(),
            secret_access_key: form.secret_access_key.trim(),
            region: form.region,
            session_token: form.session_token?.trim() || null,
          },
        });
      }
      setSaved(true);
    } catch (e) {
      setSaveError(String(e));
    } finally {
      setSaving(false);
    }
  };

  const handleTest = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      await api.health();
      setTestResult({ ok: true, message: "Backend is reachable." });
    } catch {
      setTestResult({ ok: false, message: "Backend not reachable — save credentials first." });
    } finally {
      setTesting(false);
    }
  };

  return (
    <div className={styles.page}>
      <div className={styles.pageHeader}>
        <h1 className={styles.heading}>AWS Credentials</h1>
        <p className={styles.sub}>
          Stored locally on your machine. Never sent to any external service.
        </p>
      </div>

      <div className={styles.card}>
        {/* Access Key ID */}
        <div className={styles.field}>
          <label className={styles.label}>
            AWS Access Key ID <span className={styles.req}>*</span>
          </label>
          <input
            type="text"
            className={styles.input}
            value={form.access_key_id}
            onChange={(e) => setField("access_key_id", e.target.value)}
            placeholder="AKIAIOSFODNN7EXAMPLE"
            autoComplete="off"
            spellCheck={false}
          />
        </div>

        {/* Secret Access Key */}
        <div className={styles.field}>
          <label className={styles.label}>
            AWS Secret Access Key <span className={styles.req}>*</span>
          </label>
          <div className={styles.inputRow}>
            <input
              type={showSecret ? "text" : "password"}
              className={styles.input}
              value={form.secret_access_key}
              onChange={(e) => setField("secret_access_key", e.target.value)}
              placeholder="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
              autoComplete="new-password"
              spellCheck={false}
            />
            <button
              className={styles.revealBtn}
              onClick={() => setShowSecret((v) => !v)}
              type="button"
            >
              {showSecret ? "Hide" : "Show"}
            </button>
          </div>
        </div>

        {/* Region */}
        <div className={styles.field}>
          <label className={styles.label}>
            AWS Region <span className={styles.req}>*</span>
          </label>
          <select
            className={styles.input}
            value={form.region}
            onChange={(e) => setField("region", e.target.value)}
          >
            {REGIONS.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
        </div>

        {/* Session Token (optional) */}
        <div className={styles.field}>
          <label className={styles.label}>
            Session Token{" "}
            <span className={styles.opt}>(optional — for temporary credentials)</span>
          </label>
          <div className={styles.inputRow}>
            <input
              type={showToken ? "text" : "password"}
              className={styles.input}
              value={form.session_token ?? ""}
              onChange={(e) => setField("session_token", e.target.value)}
              placeholder="Leave empty if using long-term IAM credentials"
              autoComplete="new-password"
              spellCheck={false}
            />
            <button
              className={styles.revealBtn}
              onClick={() => setShowToken((v) => !v)}
              type="button"
            >
              {showToken ? "Hide" : "Show"}
            </button>
          </div>
        </div>

        {/* Feedback */}
        {saveError && <div className={styles.error}>{saveError}</div>}
        {saved && (
          <div className={styles.success}>
            Credentials saved — backend restarted with new credentials.
          </div>
        )}
        {testResult && (
          <div className={testResult.ok ? styles.success : styles.error}>
            {testResult.message}
          </div>
        )}

        {/* Actions */}
        <div className={styles.actions}>
          <button className="btn-primary" onClick={handleSave} disabled={saving}>
            {saving ? "Saving…" : "Save Credentials"}
          </button>
          <button className="btn-secondary" onClick={handleTest} disabled={testing}>
            {testing ? "Testing…" : "Test Connection"}
          </button>
          {saved && (
            <button className="btn-secondary" onClick={() => navigate("/")}>
              Go to Dashboard →
            </button>
          )}
        </div>
      </div>

      <p className={styles.hint}>
        Need an IAM user?{" "}
        <span className={styles.hintCode}>
          Attach the <code>AmazonS3ReadOnlyAccess</code> policy (plus{" "}
          <code>s3:PutBucketLifecycleConfiguration</code>,{" "}
          <code>s3:DeleteObject</code>, <code>s3:AbortMultipartUpload</code> for
          execution).
        </span>
      </p>
    </div>
  );
}
