// Mirrors the Pydantic models defined in code/server/core/models.py

export type DroneStatus =
  | "idle"
  | "hovering"
  | "moving"
  | "landing"
  | "emergency"
  | "offline";

export type TrackingState = "live" | "stale" | "lost";

export interface Position {
  x: number;
  y: number;
  z: number;
}

export interface Velocity {
  vx: number;
  vy: number;
  vz: number;
}

export interface DroneState {
  drone_id: string;
  status: DroneStatus;
  position: Position;
  velocity: Velocity;
  battery_pct: number;
  last_seen: string; // ISO-8601 UTC string
}

export interface SwarmState {
  drones: Record<string, DroneState>;
  updated_at: string; // ISO-8601 UTC string
}

export interface HealthResponse {
  status: string;
  timestamp: string;
}

// Derived — computed client-side from last_seen age
export interface DroneSummary extends DroneState {
  tracking: TrackingState;
  age_s: number; // seconds since last telemetry
}
