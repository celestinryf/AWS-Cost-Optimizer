import type { RiskLevel } from "../types";
import styles from "./RiskBadge.module.css";

interface Props {
  level: RiskLevel;
}

export default function RiskBadge({ level }: Props) {
  return (
    <span className={`${styles.badge} ${styles[level.toLowerCase()]}`}>
      {level}
    </span>
  );
}
