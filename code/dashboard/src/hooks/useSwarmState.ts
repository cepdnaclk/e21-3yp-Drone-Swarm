import { useCallback, useEffect, useRef, useState } from "react";
import type { SwarmState } from "../types/swarm";

// Seconds before a drone is considered stale / lost
const STALE_THRESHOLD_S = 5;
const LOST_THRESHOLD_S = 30;

const WS_RECONNECT_DELAY_MS = 3_000;

export interface SwarmHookState {
  swarm: SwarmState | null;
  connected: boolean;
  error: string | null;
}

/**
 * Fetches swarm state via REST on mount, then keeps it live via WebSocket.
 * Reconnects automatically if the socket drops.
 */
export function useSwarmState(): SwarmHookState {
  const [swarm, setSwarm] = useState<SwarmState | null>(null);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const unmountedRef = useRef(false);

  // ── Initial REST fetch ──────────────────────────────────────────────────
  useEffect(() => {
    fetch("/swarm/state")
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json() as Promise<SwarmState>;
      })
      .then((data) => {
        if (!unmountedRef.current) setSwarm(data);
      })
      .catch((e: unknown) => {
        if (!unmountedRef.current)
          setError(`Initial fetch failed: ${String(e)}`);
      });
  }, []);

  // ── WebSocket live updates ──────────────────────────────────────────────
  const connect = useCallback(() => {
    if (unmountedRef.current) return;

    const protocol = window.location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${protocol}://${window.location.host}/ws/swarm`);
    wsRef.current = ws;

    ws.onopen = () => {
      if (unmountedRef.current) { ws.close(); return; }
      setConnected(true);
      setError(null);
    };

    ws.onmessage = (evt: MessageEvent<string>) => {
      try {
        const data = JSON.parse(evt.data) as SwarmState;
        if (!unmountedRef.current) setSwarm(data);
      } catch {
        // malformed frame — ignore
      }
    };

    ws.onerror = () => {
      if (!unmountedRef.current) setError("WebSocket error");
    };

    ws.onclose = () => {
      if (unmountedRef.current) return;
      setConnected(false);
      // Schedule reconnect
      reconnectTimer.current = setTimeout(connect, WS_RECONNECT_DELAY_MS);
    };
  }, []);

  useEffect(() => {
    unmountedRef.current = false;
    connect();
    return () => {
      unmountedRef.current = true;
      if (reconnectTimer.current !== null) clearTimeout(reconnectTimer.current);
      wsRef.current?.close();
    };
  }, [connect]);

  return { swarm, connected, error };
}

// ── Utility exported for components ────────────────────────────────────────

export function ageSeconds(isoTimestamp: string): number {
  return (Date.now() - new Date(isoTimestamp).getTime()) / 1_000;
}

export function trackingState(
  ageS: number
): "live" | "stale" | "lost" {
  if (ageS <= STALE_THRESHOLD_S) return "live";
  if (ageS <= LOST_THRESHOLD_S) return "stale";
  return "lost";
}
