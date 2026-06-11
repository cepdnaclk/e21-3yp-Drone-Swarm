"use client";

import { useEffect, useState } from "react";
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

const macIsValid = (mac: string) =>
  /^([0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}$/.test(mac.trim());

const makeId = () => Math.random().toString(36).slice(2, 9);

const loadFleet = (): Drone[] => {
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

const saveFleet = (fleet: Drone[]) => {
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
  const [fleet, setFleet] = useState<Drone[]>(loadFleet);
  const [draftName, setDraftName] = useState("");
  const [draftMac, setDraftMac] = useState("");
  const [draftError, setDraftError] = useState<string | null>(null);

  useEffect(() => {
    saveFleet(fleet);
    socket.emit("drone-fleet-update", {
      drones: fleet.map((d) => ({ id: d.id, mac: d.mac, active: d.active })),
    });
  }, [fleet]);

  useEffect(() => {
    const onTelemetry = (data: {
      id?: string;
      mac?: string;
      battery?: number;
      pos?: [number, number, number];
      state?: string;
    }) => {
      setFleet((prev) =>
        prev.map((d) => {
          const matches = (data.id && data.id === d.id) || (data.mac && data.mac === d.mac);
          if (!matches) return d;
          return {
            ...d,
            battery: data.battery ?? d.battery,
            pos: data.pos ?? d.pos,
            state: data.state ?? d.state,
            lastSeen: Date.now(),
          };
        })
      );
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

  const addDrone = () => {
    const name = draftName.trim();
    const mac = draftMac.trim();
    if (!name) {
      setDraftError("Name required");
      return;
    }
    if (!macIsValid(mac)) {
      setDraftError("MAC must be AA:BB:CC:DD:EE:FF");
      return;
    }
    if (fleet.some((d) => d.mac.toLowerCase() === mac.toLowerCase())) {
      setDraftError("MAC already in fleet");
      return;
    }
    setFleet((prev) => [
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
    setFleet((prev) => prev.map((d) => (d.id === id ? { ...d, ...patch } : d)));

  const removeDrone = (id: string) =>
    setFleet((prev) => prev.filter((d) => d.id !== id));

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
                      value={drone.mac}
                      onChange={(e) => updateDrone(drone.id, { mac: e.target.value })}
                    />
                  </div>

                  <div className="drone-row">
                    <span className="drone-row-label">Name</span>
                    <Form.Control
                      size="sm"
                      type="text"
                      value={drone.name}
                      onChange={(e) => updateDrone(drone.id, { name: e.target.value })}
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

                  <div className="drone-actions">
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
