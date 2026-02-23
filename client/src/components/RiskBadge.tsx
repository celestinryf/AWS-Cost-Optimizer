import type { RiskLevel } from "../types";
import styles from "./RiskBadge.module.css";

interface Props {
  level: RiskLevel;
}

export default function RiskBadge({ level }: Props) {
  const label = level.charAt(0).toUpperCase() + level.slice(1);
  return (
    <span className={`${styles.badge} ${styles[level]}`}>
      {label}
    </span>
  );
}
