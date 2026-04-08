import { useState } from "react";
import type { ScanRequest, StorageClass } from "../types";
import styles from "./ScanModal.module.css";

interface Props {
  onConfirm: (req: ScanRequest) => void;
  onClose: () => void;
  loading: boolean;
}

const STORAGE_CLASS_OPTIONS: { value: StorageClass; label: string }[] = [
  { value: "GLACIER_IR", label: "Glacier Instant Retrieval" },
  { value: "GLACIER", label: "Glacier Flexible Retrieval" },
  { value: "DEEP_ARCHIVE", label: "Glacier Deep Archive" },
  { value: "STANDARD_IA", label: "Standard-IA" },
  { value: "ONEZONE_IA", label: "One Zone-IA" },
  { value: "INTELLIGENT_TIERING", label: "Intelligent-Tiering" },
];

function parseLines(value: string): string[] {
  return value
    .split(/[\n,]+/)
    .map((s) => s.trim())
    .filter(Boolean);
}

export default function ScanModal({ onConfirm, onClose, loading }: Props) {
  const [include, setInclude] = useState("");
  const [exclude, setExclude] = useState("");
  const [maxObjects, setMaxObjects] = useState(1000);
  const [coldDays, setColdDays] = useState(90);
  const [staleDays, setStaleDays] = useState(365);
  const [multipartDays, setMultipartDays] = useState(7);
  const [targetClass, setTargetClass] = useState<StorageClass>("GLACIER_IR");
  const [showAdvanced, setShowAdvanced] = useState(false);

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    onConfirm({
      include_buckets: parseLines(include),
      exclude_buckets: parseLines(exclude),
      max_objects_per_bucket: maxObjects,
      cold_days: coldDays,
      stale_days: staleDays,
      multipart_days: multipartDays,
      target_storage_class: targetClass,
    });
  }

  return (
    <div className={styles.overlay} onClick={onClose}>
      <div className={styles.dialog} onClick={(e) => e.stopPropagation()}>
        <h2 className={styles.title}>New Scan</h2>
        <form onSubmit={handleSubmit}>
          <label className={styles.label}>
            Include buckets
            <span className={styles.hint}>(comma or newline separated; leave blank for defaults)</span>
            <textarea
              className={styles.textarea}
              value={include}
              onChange={(e) => setInclude(e.target.value)}
              placeholder="my-bucket-1, my-bucket-2"
              rows={3}
            />
          </label>

          <label className={styles.label}>
            Exclude buckets
            <textarea
              className={styles.textarea}
              value={exclude}
              onChange={(e) => setExclude(e.target.value)}
              placeholder="prod-critical-bucket"
              rows={2}
            />
          </label>

          <label className={styles.label}>
            Max objects per bucket
            <input
              type="number"
              className={styles.input}
              value={maxObjects}
              min={1}
              max={10000}
              onChange={(e) => setMaxObjects(Number(e.target.value))}
            />
          </label>

          <button
            type="button"
            className={styles.toggleBtn}
            onClick={() => setShowAdvanced(!showAdvanced)}
          >
            {showAdvanced ? "Hide" : "Show"} advanced thresholds
          </button>

          {showAdvanced && (
            <div className={styles.advanced}>
              <label className={styles.label}>
                Cold object threshold (days)
                <span className={styles.hint}>STANDARD objects older than this get storage class change recommendations</span>
                <input
                  type="number"
                  className={styles.input}
                  value={coldDays}
                  min={0}
                  max={3650}
                  onChange={(e) => setColdDays(Number(e.target.value))}
                />
              </label>

              <label className={styles.label}>
                Stale object threshold (days)
                <span className={styles.hint}>Objects older than this get delete recommendations</span>
                <input
                  type="number"
                  className={styles.input}
                  value={staleDays}
                  min={0}
                  max={3650}
                  onChange={(e) => setStaleDays(Number(e.target.value))}
                />
              </label>

              <label className={styles.label}>
                Incomplete upload threshold (days)
                <span className={styles.hint}>Multipart uploads older than this get abort recommendations</span>
                <input
                  type="number"
                  className={styles.input}
                  value={multipartDays}
                  min={0}
                  max={365}
                  onChange={(e) => setMultipartDays(Number(e.target.value))}
                />
              </label>

              <label className={styles.label}>
                Target storage class
                <select
                  className={styles.select}
                  value={targetClass}
                  onChange={(e) => setTargetClass(e.target.value as StorageClass)}
                >
                  {STORAGE_CLASS_OPTIONS.map((opt) => (
                    <option key={opt.value} value={opt.value}>
                      {opt.label}
                    </option>
                  ))}
                </select>
              </label>
            </div>
          )}

          <div className={styles.actions}>
            <button type="button" className="btn-secondary" onClick={onClose}>
              Cancel
            </button>
            <button type="submit" className="btn-primary" disabled={loading}>
              {loading ? "Scanning…" : "Start Scan"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
