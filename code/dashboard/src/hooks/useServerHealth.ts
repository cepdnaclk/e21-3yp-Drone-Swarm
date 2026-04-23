import { useEffect, useRef, useState } from "react";
import type { HealthResponse } from "../types/swarm";

export type ServerStatus = "online" | "offline" | "checking";

export interface HealthState {
  status: ServerStatus;
  lastChecked: Date | null;
}

const POLL_INTERVAL_MS = 5_000;

/** Polls GET /health every 5 s and reports server reachability. */
export function useServerHealth(): HealthState {
  const [state, setState] = useState<HealthState>({
    status: "checking",
    lastChecked: null,
  });
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const check = async () => {
    try {
      const res = await fetch("/health", { signal: AbortSignal.timeout(3_000) });
      if (res.ok) {
        const _data: HealthResponse = await res.json();
        setState({ status: "online", lastChecked: new Date() });
      } else {
        setState({ status: "offline", lastChecked: new Date() });
      }
    } catch {
      setState({ status: "offline", lastChecked: new Date() });
    }
  };

  useEffect(() => {
    check();
    timerRef.current = setInterval(check, POLL_INTERVAL_MS);
    return () => {
      if (timerRef.current !== null) clearInterval(timerRef.current);
    };
  }, []);

  return state;
}
