import { useState } from "react";
import type { ScanRequest } from "../types";
import styles from "./ScanModal.module.css";

interface Props {
  onConfirm: (req: ScanRequest) => void;
  onClose: () => void;
  loading: boolean;
}

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

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    onConfirm({
      include_buckets: parseLines(include),
      exclude_buckets: parseLines(exclude),
      max_objects: maxObjects,
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
