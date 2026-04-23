import { useMemo } from "react";
import type { SwarmState } from "../types/swarm";
import { ageSeconds, trackingState } from "../hooks/useSwarmState";
import { BatteryBar } from "./BatteryBar";
import { DroneStatusBadge, TrackingBadge } from "./StatusBadge";
import styles from "./DroneTable.module.css";

interface Props {
  swarm: SwarmState | null;
}

export function DroneTable({ swarm }: Props) {
  // Recompute derived tracking fields every render (clock-driven via parent tick)
  const rows = useMemo(() => {
    if (!swarm) return [];
    return Object.values(swarm.drones).map((d) => {
      const ageS = ageSeconds(d.last_seen);
      return { ...d, ageS, tracking: trackingState(ageS) } as const;
    });
  }, [swarm]);

  if (!swarm) {
    return <p className={styles.empty}>Loading swarm state…</p>;
  }

  if (rows.length === 0) {
    return <p className={styles.empty}>No drones connected yet.</p>;
  }

  return (
    <div className={styles.scroll}>
      <table className={styles.table}>
        <thead>
          <tr>
            <th>Drone ID</th>
            <th>Status</th>
            <th>Tracking</th>
            <th>Position (m)</th>
            <th>Battery</th>
            <th>Last seen</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((drone) => (
            <tr key={drone.drone_id} className={styles[`row_${drone.tracking}`]}>
              <td className={styles.droneId}>{drone.drone_id}</td>

              <td>
                <DroneStatusBadge value={drone.status} />
              </td>

              <td>
                <TrackingBadge value={drone.tracking} ageS={drone.ageS} />
              </td>

              <td className={styles.position}>
                <span title="X">x&nbsp;{drone.position.x.toFixed(2)}</span>
                <span title="Y">y&nbsp;{drone.position.y.toFixed(2)}</span>
                <span title="Z">z&nbsp;{drone.position.z.toFixed(2)}</span>
              </td>

              <td>
                <BatteryBar pct={drone.battery_pct} />
              </td>

              <td className={styles.lastSeen}>
                {new Date(drone.last_seen).toLocaleTimeString()}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
