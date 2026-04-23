import type { HealthState } from "../hooks/useServerHealth";
import styles from "./HealthBadge.module.css";

interface Props {
  health: HealthState;
  wsConnected: boolean;
}

export function HealthBadge({ health, wsConnected }: Props) {
  const serverLabel =
    health.status === "checking" ? "Checking…" :
    health.status === "online"   ? "Server online" :
                                   "Server offline";

  const wsLabel = wsConnected ? "WS live" : "WS disconnected";

  return (
    <div className={styles.row}>
      <span className={`${styles.badge} ${styles[health.status]}`}>
        <span className={styles.dot} />
        {serverLabel}
      </span>

      <span className={`${styles.badge} ${wsConnected ? styles.online : styles.offline}`}>
        <span className={styles.dot} />
        {wsLabel}
      </span>

      {health.lastChecked && (
        <span className={styles.meta}>
          Last checked {health.lastChecked.toLocaleTimeString()}
        </span>
      )}
    </div>
  );
}
