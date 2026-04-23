import type { SwarmState } from "../types/swarm";
import styles from "./SwarmSummary.module.css";

interface Props {
  swarm: SwarmState | null;
}

export function SwarmSummary({ swarm }: Props) {
  if (!swarm) return null;

  const drones = Object.values(swarm.drones);
  const total   = drones.length;
  const active  = drones.filter((d) => d.status !== "offline").length;
  const offline = total - active;
  const emergency = drones.filter((d) => d.status === "emergency").length;
  const avgBattery =
    total > 0
      ? drones.reduce((s, d) => s + d.battery_pct, 0) / total
      : 0;

  return (
    <div className={styles.grid}>
      <Stat label="Total drones"  value={total}                    />
      <Stat label="Active"        value={active}  color="green"    />
      <Stat label="Offline"       value={offline} color={offline  > 0 ? "amber" : undefined} />
      <Stat label="Emergency"     value={emergency} color={emergency > 0 ? "red"  : undefined} />
      <Stat label="Avg. battery"  value={`${avgBattery.toFixed(0)}%`} />
      <Stat
        label="Updated"
        value={new Date(swarm.updated_at).toLocaleTimeString()}
        small
      />
    </div>
  );
}

interface StatProps {
  label: string;
  value: string | number;
  color?: "green" | "amber" | "red";
  small?: boolean;
}

function Stat({ label, value, color, small }: StatProps) {
  return (
    <div className={styles.card}>
      <span className={styles.label}>{label}</span>
      <span className={`${styles.value} ${color ? styles[color] : ""} ${small ? styles.small : ""}`}>
        {value}
      </span>
    </div>
  );
}
