import { useEffect, useState } from "react";
import { useServerHealth } from "../hooks/useServerHealth";
import { useSwarmState } from "../hooks/useSwarmState";
import { HealthBadge } from "../components/HealthBadge";
import { SwarmSummary } from "../components/SwarmSummary";
import { DroneTable } from "../components/DroneTable";
import styles from "./Dashboard.module.css";

// Re-render every second so age columns stay current without a WS tick
const CLOCK_INTERVAL_MS = 1_000;

export function Dashboard() {
  const health = useServerHealth();
  const { swarm, connected, error } = useSwarmState();

  // Clock tick: forces re-render so "age" cells update in real time
  useClockTick(CLOCK_INTERVAL_MS);

  const droneCount = swarm ? Object.keys(swarm.drones).length : null;

  return (
    <div className={styles.page}>
      {/* Header */}
      <header className={styles.header}>
        <div className={styles.titleBlock}>
          <h1 className={styles.title}>Drone Swarm</h1>
          <span className={styles.subtitle}>Control Dashboard</span>
        </div>
        <HealthBadge health={health} wsConnected={connected} />
      </header>

      {/* Error banner */}
      {error && (
        <div className={styles.errorBanner} role="alert">
          {error}
        </div>
      )}

      <main className={styles.main}>
        {/* Summary stat cards */}
        <section>
          <SectionHeading>Swarm overview</SectionHeading>
          <SwarmSummary swarm={swarm} />
        </section>

        {/* Per-drone table */}
        <section>
          <SectionHeading>
            Drones
            {droneCount !== null && (
              <span className={styles.count}>{droneCount}</span>
            )}
          </SectionHeading>
          <DroneTable swarm={swarm} />
        </section>
      </main>
    </div>
  );
}

// ── Helpers ────────────────────────────────────────────────────────────────

function SectionHeading({ children }: { children: React.ReactNode }) {
  return <h2 className={styles.sectionHeading}>{children}</h2>;
}

function useClockTick(ms: number) {
  const [, setTick] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setTick((n) => n + 1), ms);
    return () => clearInterval(id);
  }, [ms]);
}
