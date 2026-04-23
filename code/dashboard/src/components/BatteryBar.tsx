import styles from "./BatteryBar.module.css";

interface Props {
  pct: number; // 0–100
}

export function BatteryBar({ pct }: Props) {
  const level =
    pct <= 15 ? "critical" :
    pct <= 30 ? "low"      :
    pct <= 60 ? "medium"   :
                "high";

  return (
    <div className={styles.wrapper} title={`${pct.toFixed(1)}%`}>
      <div className={styles.track}>
        <div
          className={`${styles.fill} ${styles[level]}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className={styles.label}>{pct.toFixed(0)}%</span>
    </div>
  );
}
