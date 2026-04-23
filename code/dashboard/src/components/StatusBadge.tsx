import type { DroneStatus, TrackingState } from "../types/swarm";
import styles from "./StatusBadge.module.css";

interface DroneStatusProps { value: DroneStatus; }
interface TrackingProps    { value: TrackingState; ageS: number; }

export function DroneStatusBadge({ value }: DroneStatusProps) {
  return (
    <span className={`${styles.badge} ${styles[value]}`}>
      {value}
    </span>
  );
}

export function TrackingBadge({ value, ageS }: TrackingProps) {
  const label =
    value === "live"  ? `Live (${ageS.toFixed(1)}s)` :
    value === "stale" ? `Stale (${ageS.toFixed(0)}s)` :
                        `Lost (${ageS.toFixed(0)}s)`;

  return (
    <span className={`${styles.badge} ${styles[`tracking_${value}`]}`}>
      {label}
    </span>
  );
}
