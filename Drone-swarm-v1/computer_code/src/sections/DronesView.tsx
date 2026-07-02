"use client";

import { useEffect, useRef, useState } from "react";
import { Card, Col, Form, Row } from "react-bootstrap";

import { socket } from "../shared/styles/scripts/socket";

type Drone = {
  id: string;
  name: string;
  mac: string;
  active: boolean;
  battery: number | null;
  pos: [number, number, number] | null;
  state: string;
  lastSeen: number | null;
};

const STORAGE_KEY = "drone-swarm-fleet-v1";

const normaliseMac = (mac: string) =>
  mac.trim().toUpperCase().replace(/-/g, ":");

const macIsValid = (mac: string) =>
  /^([0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}$/.test(mac.trim());

const makeId = () => Math.random().toString(36).slice(2, 9);

const loadCachedFleet = (): Drone[] => {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (Array.isArray(parsed)) return parsed as Drone[];
  } catch {
    // ignore
  }
  return [];
};

const saveCachedFleet = (fleet: Drone[]) => {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(fleet));
  } catch {
    // ignore
  }
};

const formatPos = (pos: Drone["pos"]) =>
  pos ? `${pos[0].toFixed(2)}, ${pos[1].toFixed(2)}, ${pos[2].toFixed(2)}` : "—";

const formatLastSeen = (ts: number | null) => {
  if (!ts) return "never";
  const dt = (Date.now() - ts) / 1000;
  if (dt < 1) return "just now";
  if (dt < 60) return `${Math.floor(dt)}s ago`;
  if (dt < 3600) return `${Math.floor(dt / 60)}m ago`;
  return `${Math.floor(dt / 3600)}h ago`;
};

const batteryTone = (battery: number | null) => {
  if (battery == null) return "battery-empty";
  if (battery > 60) return "battery-good";
  if (battery > 25) return "battery-warn";
  return "battery-bad";
};

export default function DronesView() {
  const [fleet, setFleet] = useState<Drone[]>(loadCachedFleet);
  const [draftName, setDraftName] = useState("");
  const [draftMac, setDraftMac] = useState("");
  const [draftError, setDraftError] = useState<string | null>(null);
  // Becomes true once we've heard the canonical fleet from the backend (or have
  // taken a local action). Until then, edits aren't broadcast to avoid clobbering
  // the server's view with our cached state on first connect.
  const hydratedRef = useRef(false);
  const suppressNextEmitRef = useRef(false);

  useEffect(() => {
    const onFleet = (data: { drones?: Drone[] }) => {
      const incoming = Array.isArray(data?.drones) ? data.drones : [];
      setFleet((prev) => {
        // Merge: server is source of truth for membership + name + active flag;
        // we keep our runtime telemetry (battery/pos/state/lastSeen) locally.
        const byMac: Record<string, Drone> = {};
        prev.forEach((d) => {
          byMac[normaliseMac(d.mac)] = d;
        });
        const merged: Drone[] = incoming.map((entry: any) => {
          const mac = normaliseMac(String(entry.mac ?? ""));
          const existing = byMac[mac];
          return {
            id: String(entry.id ?? mac.replace(/:/g, "").toLowerCase()),
            name: String(entry.name ?? mac),
            mac,
            active: Boolean(entry.active),
            battery: existing?.battery ?? null,
            pos: existing?.pos ?? null,
            state: existing?.state ?? "OFFLINE",
            lastSeen: existing?.lastSeen ?? null,
          };
        });
        suppressNextEmitRef.current = true;
        return merged;
      });
      hydratedRef.current = true;
    };
    socket.on("fleet", onFleet);
    return () => {
      socket.off("fleet", onFleet);
    };
  }, []);

  useEffect(() => {
    saveCachedFleet(fleet);
    if (!hydratedRef.current) return;
    if (suppressNextEmitRef.current) {
      suppressNextEmitRef.current = false;
      return;
    }
    socket.emit("drone-fleet-update", {
      drones: fleet.map((d) => ({
        id: d.id,
        name: d.name,
        mac: d.mac,
        active: d.active,
      })),
    });
  }, [fleet]);

  useEffect(() => {
    const onTelemetry = (data: {
      id?: string;
      mac?: string;
      battery?: number;
      battery_mv?: number;
      pos?: [number, number, number];
      state?: string;
    }) => {
      const dataMac = data.mac ? normaliseMac(data.mac) : null;
      setFleet((prev) => {
        suppressNextEmitRef.current = true;
        return prev.map((d) => {
          const matches =
            (data.id && data.id === d.id) ||
            (dataMac && dataMac === normaliseMac(d.mac));
          if (!matches) return d;
          return {
            ...d,
            battery: data.battery ?? d.battery,
            pos: data.pos ?? d.pos,
            state: data.state ?? d.state,
            lastSeen: Date.now(),
          };
        });
      });
    };
    socket.on("drone-telemetry", onTelemetry);
    return () => {
      socket.off("drone-telemetry", onTelemetry);
    };
  }, []);

  useEffect(() => {
    const id = setInterval(() => {
      setFleet((prev) => prev.slice());
    }, 5000);
    return () => clearInterval(id);
  }, []);

  // Wraps setFleet so that user edits ALWAYS reach the server, even right after
  // a telemetry packet or a fleet broadcast (which set suppressNextEmitRef).
  const userEdit = (updater: (prev: Drone[]) => Drone[]) => {
    hydratedRef.current = true;
    suppressNextEmitRef.current = false;
    setFleet(updater);
  };

  const addDrone = () => {
    const name = draftName.trim();
    const mac = normaliseMac(draftMac);
    if (!name) {
      setDraftError("Name required");
      return;
    }
    if (!macIsValid(mac)) {
      setDraftError("MAC must be AA:BB:CC:DD:EE:FF");
      return;
    }
    if (fleet.some((d) => normaliseMac(d.mac) === mac)) {
      setDraftError("MAC already in fleet");
      return;
    }
    userEdit((prev) => [
      ...prev,
      {
        id: makeId(),
        name,
        mac,
        active: true,
        battery: null,
        pos: null,
        state: "OFFLINE",
        lastSeen: null,
      },
    ]);
    setDraftName("");
    setDraftMac("");
    setDraftError(null);
  };

  const updateDrone = (id: string, patch: Partial<Drone>) =>
    userEdit((prev) => prev.map((d) => (d.id === id ? { ...d, ...patch } : d)));

  const removeDrone = (id: string) =>
    userEdit((prev) => prev.filter((d) => d.id !== id));

  // Per-card edit buffers — name/MAC edits are staged here until the user
  // clicks Update on that card. The active switch + Remove still commit
  // immediately because they're one-shot intents.
  type CardDraft = { name: string; mac: string };
  const [drafts, setDrafts] = useState<Record<string, CardDraft>>({});
  const [cardErrors, setCardErrors] = useState<Record<string, string | null>>({});

  // Keep drafts in sync with the fleet: seed a draft for any new drone, drop
  // drafts for drones that disappeared. Existing drafts are left alone so an
  // in-flight server push doesn't wipe what the user is typing.
  useEffect(() => {
    setDrafts((prev) => {
      const next = { ...prev };
      let changed = false;
      for (const d of fleet) {
        if (!next[d.id]) {
          next[d.id] = { name: d.name, mac: d.mac };
          changed = true;
        }
      }
      for (const id of Object.keys(next)) {
        if (!fleet.some((d) => d.id === id)) {
          delete next[id];
          changed = true;
        }
      }
      return changed ? next : prev;
    });
  }, [fleet]);

  const setDraftField = (id: string, patch: Partial<CardDraft>) => {
    setDrafts((prev) => ({
      ...prev,
      [id]: { ...(prev[id] ?? { name: "", mac: "" }), ...patch },
    }));
    setCardErrors((prev) => ({ ...prev, [id]: null }));
  };

  const isDirty = (drone: Drone) => {
    const d = drafts[drone.id];
    if (!d) return false;
    return (
      d.name !== drone.name ||
      normaliseMac(d.mac) !== normaliseMac(drone.mac)
    );
  };

  const commitDraft = (drone: Drone) => {
    const draft = drafts[drone.id];
    if (!draft) return;
    const name = draft.name.trim();
    const mac = normaliseMac(draft.mac);
    if (!name) {
      setCardErrors((prev) => ({ ...prev, [drone.id]: "Name required" }));
      return;
    }
    if (!macIsValid(mac)) {
      setCardErrors((prev) => ({
        ...prev,
        [drone.id]: "MAC must be AA:BB:CC:DD:EE:FF",
      }));
      return;
    }
    if (
      fleet.some(
        (other) => other.id !== drone.id && normaliseMac(other.mac) === mac
      )
    ) {
      setCardErrors((prev) => ({
        ...prev,
        [drone.id]: "MAC already in fleet",
      }));
      return;
    }
    setCardErrors((prev) => ({ ...prev, [drone.id]: null }));
    setDrafts((prev) => ({ ...prev, [drone.id]: { name, mac } }));
    updateDrone(drone.id, { name, mac });
  };

  const revertDraft = (drone: Drone) => {
    setDrafts((prev) => ({
      ...prev,
      [drone.id]: { name: drone.name, mac: drone.mac },
    }));
    setCardErrors((prev) => ({ ...prev, [drone.id]: null }));
  };

  const activeCount = fleet.filter((d) => d.active).length;

  return (
    <>
      <Row className="app-header g-3 align-items-center">
        <Col md="auto" className="brand-block">
          <div className="brand-mark">
            <span>Fleet manager</span>
          </div>
          <h2 className="app-title">Drones</h2>
        </Col>
        <Col>
          <div className="status-strip">
            <span className="status-pill">
              <span className="status-label">Registered</span>
              <b>{fleet.length}</b>
            </span>
            <span className="status-pill">
              <span className="status-label">Active</span>
              <b>{activeCount}</b>
            </span>
            <span className="status-pill">
              <span className="status-label">Online</span>
              <b>
                {fleet.filter((d) => d.lastSeen && Date.now() - d.lastSeen < 5000).length}
              </b>
            </span>
          </div>
        </Col>
      </Row>

      <Row className="g-4">
        <Col xs={12}>
          <Card className="app-panel shadow-sm mb-3">
            <Card.Body className="p-3">
              <h5 className="panel-heading">Add drone</h5>
              <Row className="g-2 align-items-end">
                <Col md={3}>
                  <Form.Label>Name</Form.Label>
                  <Form.Control
                    type="text"
                    placeholder="alpha"
                    value={draftName}
                    onChange={(e) => setDraftName(e.target.value)}
                  />
                </Col>
                <Col md={4}>
                  <Form.Label>MAC address</Form.Label>
                  <Form.Control
                    type="text"
                    placeholder="AA:BB:CC:DD:EE:FF"
                    value={draftMac}
                    onChange={(e) => setDraftMac(e.target.value)}
                  />
                </Col>
                <Col md="auto">
                  <button type="button" className="btn btn-primary" onClick={addDrone}>
                    Add drone
                  </button>
                </Col>
                {draftError && (
                  <Col md="auto">
                    <span className="form-error">{draftError}</span>
                  </Col>
                )}
              </Row>
            </Card.Body>
          </Card>
        </Col>
      </Row>

      {fleet.length === 0 ? (
        <Row>
          <Col>
            <Card className="app-panel shadow-sm">
              <Card.Body className="p-4">
                <div className="empty-state">
                  No drones registered yet. Add one above to get started.
                </div>
              </Card.Body>
            </Card>
          </Col>
        </Row>
      ) : (
        <Row className="g-4">
          {fleet.map((drone) => (
            <Col md={6} lg={4} key={drone.id}>
              <Card className="app-panel shadow-sm h-100">
                <Card.Body className="p-3">
                  <Row className="panel-heading align-items-center">
                    <Col>
                      <h5 className="mb-0">{drone.name || "—"}</h5>
                    </Col>
                    <Col xs="auto">
                      <Form.Check
                        type="switch"
                        id={`active-${drone.id}`}
                        label={drone.active ? "Active" : "Standby"}
                        checked={drone.active}
                        onChange={(e) => updateDrone(drone.id, { active: e.target.checked })}
                      />
                    </Col>
                  </Row>

                  <div className="drone-row">
                    <span className="drone-row-label">MAC</span>
                    <Form.Control
                      size="sm"
                      type="text"
                      value={drafts[drone.id]?.mac ?? drone.mac}
                      onChange={(e) =>
                        setDraftField(drone.id, { mac: e.target.value })
                      }
                    />
                  </div>

                  <div className="drone-row">
                    <span className="drone-row-label">Name</span>
                    <Form.Control
                      size="sm"
                      type="text"
                      value={drafts[drone.id]?.name ?? drone.name}
                      onChange={(e) =>
                        setDraftField(drone.id, { name: e.target.value })
                      }
                    />
                  </div>

                  <div className="drone-row">
                    <span className="drone-row-label">Battery</span>
                    <div className={`battery-meter ${batteryTone(drone.battery)}`}>
                      <div
                        className="battery-fill"
                        style={{ width: `${drone.battery ?? 0}%` }}
                      />
                      <span className="battery-text">
                        {drone.battery == null ? "—" : `${Math.round(drone.battery)}%`}
                      </span>
                    </div>
                  </div>

                  <div className="drone-row">
                    <span className="drone-row-label">Position</span>
                    <span className="drone-row-value mono">{formatPos(drone.pos)}</span>
                  </div>

                  <div className="drone-row">
                    <span className="drone-row-label">State</span>
                    <span className="drone-row-value">{drone.state}</span>
                  </div>

                  <div className="drone-row">
                    <span className="drone-row-label">Last seen</span>
                    <span className="drone-row-value">{formatLastSeen(drone.lastSeen)}</span>
                  </div>

                  {cardErrors[drone.id] && (
                    <div className="drone-row-error">
                      <span className="form-error">{cardErrors[drone.id]}</span>
                    </div>
                  )}

                  <div className="drone-actions">
                    <button
                      type="button"
                      className="btn btn-sm btn-outline-secondary"
                      onClick={() => revertDraft(drone)}
                      disabled={!isDirty(drone)}
                    >
                      Revert
                    </button>
                    <button
                      type="button"
                      className="btn btn-sm btn-primary"
                      onClick={() => commitDraft(drone)}
                      disabled={!isDirty(drone)}
                    >
                      {isDirty(drone) ? "Update" : "Saved"}
                    </button>
                    <button
                      type="button"
                      className="btn btn-sm btn-outline-danger"
                      onClick={() => removeDrone(drone.id)}
                    >
                      Remove
                    </button>
                  </div>
                </Card.Body>
              </Card>
            </Col>
          ))}
        </Row>
      )}
    </>
  );
}
