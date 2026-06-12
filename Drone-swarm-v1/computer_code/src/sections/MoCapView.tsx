"use client";

import { useEffect, useState } from "react";
import { Card, Col, Form, Row } from "react-bootstrap";
import { Canvas } from "@react-three/fiber";
import { OrbitControls, Stats } from "@react-three/drei";

import CameraWireframe from "../components/CameraWireframe";
import { socket } from "../shared/styles/scripts/socket";

type FleetEntry = {
  id: string;
  name: string;
  mac: string;
  active: boolean;
};

const normaliseMac = (mac: string) =>
  mac.trim().toUpperCase().replace(/-/g, ":");

const PID_LABELS = [
  "Kp pos xy", "Ki pos xy", "Kd pos xy",
  "Kp pos z", "Ki pos z", "Kd pos z",
  "Kp yaw", "Ki yaw", "Kd yaw",
  "Kp vel xy", "Ki vel xy", "Kd vel xy",
  "Kp vel z", "Ki vel z", "Kd vel z",
  "ground eff coef",
  "ground eff offset",
];

const DEFAULT_PID = [
  "2.5", "0.0", "0.4",
  "3.5", "0.5", "0.5",
  "80", "10", "5",
  "8", "1", "0.3",
  "120", "40", "20",
  "0", "0",
];

type DroneState = {
  pos: number[] | null;
  vel: number[] | null;
  heading: number | null;
  heading_age: number | null;
  sticks: number[] | null;
  state: string;
  fps: number;
  tracker_fresh: boolean;
};

const NUM_CAMERAS = 4;
const DEFAULT_THRESHOLD = 180;

// Build an OpenCV-convention camera pose (R = camera-axes-in-world, t = centre in world)
// that points the camera at `target` from `eye`. World is Z-up; camera is +z forward,
// +x right, +y down. Used to render placeholder camera wireframes before the backend
// has streamed real calibration poses.
const buildLookAtPose = (eye: [number, number, number], target: [number, number, number]) => {
  const sub = (a: number[], b: number[]) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
  const cross = (a: number[], b: number[]) => [
    a[1] * b[2] - a[2] * b[1],
    a[2] * b[0] - a[0] * b[2],
    a[0] * b[1] - a[1] * b[0],
  ];
  const norm = (v: number[]) => {
    const l = Math.hypot(v[0], v[1], v[2]) || 1;
    return [v[0] / l, v[1] / l, v[2] / l];
  };
  const worldUp = [0, 0, 1];
  const forward = norm(sub(target, eye));            // camera +z
  let right = cross(worldUp, forward);               // camera +x
  if (Math.hypot(right[0], right[1], right[2]) < 1e-6) right = [1, 0, 0];
  right = norm(right);
  const down = norm(cross(right, forward));          // camera +y
  // R columns are right, down, forward.
  const R: number[][] = [
    [right[0], down[0], forward[0]],
    [right[1], down[1], forward[1]],
    [right[2], down[2], forward[2]],
  ];
  return { R, t: [eye[0], eye[1], eye[2]] };
};

// 4 cameras at the corners of a 2 m × 2 m square at ~1.5 m height, all aimed at
// the floor centre. Replaced by real calibration poses as soon as the backend
// emits "camera-pose".
const FALLBACK_CAMERA_POSES: { R: number[][]; t: number[] }[] = [
  buildLookAtPose([ 1.0,  1.0, 1.5], [0, 0, 0.3]),
  buildLookAtPose([-1.0,  1.0, 1.5], [0, 0, 0.3]),
  buildLookAtPose([-1.0, -1.0, 1.5], [0, 0, 0.3]),
  buildLookAtPose([ 1.0, -1.0, 1.5], [0, 0, 0.3]),
];

export default function MoCapView() {
  const [cameraStreamRunning, setCameraStreamRunning] = useState(false);
  const [cameraThresholds, setCameraThresholds] = useState<number[]>(
    () => Array(NUM_CAMERAS).fill(DEFAULT_THRESHOLD),
  );
  const [saveStatus, setSaveStatus] = useState<"idle" | "saved">("idle");

  const [cameraPoses, setCameraPoses] = useState<{ R: number[][]; t: number[] }[]>([]);
  const [, setToWorldCoordsMatrix] = useState<number[][] | null>(null);

  const [droneState, setDroneState] = useState<DroneState>({
    pos: null,
    vel: null,
    heading: null,
    heading_age: null,
    sticks: null,
    state: "IDLE",
    fps: 0,
    tracker_fresh: false,
  });

  const [droneArmed, setDroneArmed] = useState(false);
  const [takeoffZ, setTakeoffZ] = useState("0.20");
  const [dronePID, setDronePID] = useState<string[]>(DEFAULT_PID);
  const [droneSetpoint, setDroneSetpoint] = useState<string[]>(["0", "0", "0.20"]);
  const [droneTrim, setDroneTrim] = useState<string[]>(["0", "0", "0", "0"]);

  const [fleet, setFleet] = useState<FleetEntry[]>([]);
  const [selectedMac, setSelectedMac] = useState<string>("");

  const handleSelectDrone = (mac: string) => {
    setSelectedMac(mac);
    if (mac) {
      socket.emit("mocap-select-drone", { mac });
    }
  };

  useEffect(() => {
    const onFleet = (data: { drones?: FleetEntry[]; selected_mac?: string | null }) => {
      const drones = Array.isArray(data?.drones)
        ? data.drones.map((d) => ({ ...d, mac: normaliseMac(d.mac) }))
        : [];
      setFleet(drones);
      if (data.selected_mac) {
        // Backend owns the selection — mirror it.
        setSelectedMac(normaliseMac(data.selected_mac));
      } else if (!selectedMac && drones.length > 0) {
        // No backend selection yet: pick the first ACTIVE drone and tell the
        // backend, so the radio is actually retargeted — a display-only pick
        // would let commands go to whatever drone the sender last targeted.
        const firstActive = drones.find((d) => d.active);
        if (firstActive) {
          handleSelectDrone(firstActive.mac);
        }
      }
    };
    socket.on("fleet", onFleet);
    return () => {
      socket.off("fleet", onFleet);
    };
  }, [selectedMac]);

  useEffect(() => {
    socket.on("camera-pose", (data) => {
      setCameraPoses(data.camera_poses ?? []);
    });
    socket.on("to-world-coords-matrix", (data) => {
      setToWorldCoordsMatrix(data.to_world_coords_matrix ?? null);
    });
    socket.on("drone-state", (data: DroneState) => {
      setDroneState(data);
    });
    return () => {
      socket.off("camera-pose");
      socket.off("to-world-coords-matrix");
      socket.off("drone-state");
    };
  }, []);

  useEffect(() => {
    socket.emit("arm-drone", { armed: droneArmed });
    const id = setInterval(() => socket.emit("arm-drone", { armed: droneArmed }), 500);
    return () => clearInterval(id);
  }, [droneArmed]);

  useEffect(() => {
    socket.emit("set-drone-trim", { droneTrim: droneTrim.map((x) => parseInt(x, 10)) });
  }, [droneTrim]);

  useEffect(() => {
    socket.emit("set-drone-setpoint", { droneSetpoint: droneSetpoint.map((x) => parseFloat(x)) });
  }, [droneSetpoint]);

  useEffect(() => {
    socket.emit("update-camera-settings", {
      thresholds: cameraThresholds.map((v) => Math.round(v)),
    });
  }, [cameraThresholds]);

  const saveSettings = () => {
    socket.emit("update-camera-settings", {
      thresholds: cameraThresholds.map((v) => Math.round(v)),
    });
    socket.emit("set-drone-pid", { dronePID: dronePID.map((x) => parseFloat(x)) });
    setSaveStatus("saved");
    window.setTimeout(() => setSaveStatus("idle"), 1500);
  };

  const fmt = (x: number | null | undefined, digits = 3) =>
    x === null || x === undefined || Number.isNaN(x) ? "-" : x.toFixed(digits);

  const fmtArr = (xs: number[] | null | undefined, digits = 3) =>
    xs ? xs.map((x) => fmt(x, digits)).join(", ") : "-";

  const sendTakeoff = () => {
    const z = parseFloat(takeoffZ);
    if (Number.isFinite(z) && z > 0) {
      socket.emit("takeoff", { z });
    }
  };

  const sendLand = () => socket.emit("land", {});

  return (
    <>
      <Row className="app-header g-3 align-items-center">
        <Col md="auto" className="brand-block">
          <div className="brand-mark">
            <span>Drone Configurator</span>
          </div>
          <h2 className="app-title">MoCap single drone</h2>
        </Col>
        <Col md="auto" className="mocap-drone-select">
          <Form.Label className="mocap-drone-select-label">Drone</Form.Label>
          {fleet.length === 0 ? (
            <span className="mocap-drone-empty">
              No drones registered — add one in the Drones section.
            </span>
          ) : (
            <Form.Select
              size="sm"
              value={selectedMac}
              onChange={(e) => handleSelectDrone(e.target.value)}
            >
              <option value="" disabled>
                Select a drone
              </option>
              {fleet.map((d) => (
                <option
                  key={d.mac}
                  value={d.mac}
                  disabled={!d.active}
                >
                  {d.name} — {d.mac}
                  {d.active ? "" : " (standby)"}
                </option>
              ))}
            </Form.Select>
          )}
        </Col>
        <Col>
          <div className="status-strip">
            <span className="status-pill">
              <span className="status-label">State</span>
              <b>{droneState.state}</b>
            </span>
            <span className="status-pill">
              <span className="status-label">FPS</span>
              {fmt(droneState.fps, 1)}
            </span>
            <span className="status-pill">
              <span className="status-label">Tracker</span>
              {droneState.tracker_fresh ? "Online" : "Idle"}
            </span>
            <span className="status-pill">
              <span className="status-label">Heading age</span>
              {fmt(droneState.heading_age, 2)} s
            </span>
          </div>
        </Col>
        <Col md="auto">
          <button
            type="button"
            className={`btn ${saveStatus === "saved" ? "btn-success" : "btn-primary"}`}
            onClick={saveSettings}
            disabled={!selectedMac && fleet.length > 0}
          >
            {saveStatus === "saved" ? "Saved" : "Save settings"}
          </button>
        </Col>
      </Row>

      <Row className="g-4 align-items-stretch">
        <Col md={6} className="d-flex">
          <Card className="app-panel shadow-sm mb-3 flex-fill">
            <Card.Body className="p-3 d-flex flex-column">
              <Row className="panel-heading align-items-center">
                <Col xs="auto">
                  <h5>Camera stream</h5>
                </Col>
                <Col className="panel-toolbar">
                  <button
                    type="button"
                    className={`btn btn-sm ${cameraStreamRunning ? "btn-outline-danger" : "btn-outline-primary"}`}
                    onClick={() => setCameraStreamRunning(!cameraStreamRunning)}
                  >
                    {cameraStreamRunning ? "Stop" : "Start"}
                  </button>
                </Col>
              </Row>
              <Row className="mt-3 panel-content" style={{ minHeight: 320 }}>
                <Col>
                  {cameraStreamRunning ? (
                    <img
                      src="http://localhost:3001/api/camera-stream"
                      className="camera-frame"
                      alt="camera stream"
                    />
                  ) : (
                    <div className="camera-placeholder">Camera stream stopped</div>
                  )}
                </Col>
              </Row>
              <h6 className="section-subhead mt-3">Per-camera thresholds</h6>
              {cameraThresholds.map((value, i) => (
                <Row key={i} className="align-items-center mb-1">
                  <Col xs={2}>
                    <small>cam{i + 1}</small>
                  </Col>
                  <Col>
                    <Form.Range
                      min={0}
                      max={250}
                      value={value}
                      className="threshold-slider"
                      onChange={(e) => {
                        const next = cameraThresholds.slice();
                        next[i] = parseInt(e.target.value, 10);
                        setCameraThresholds(next);
                      }}
                    />
                  </Col>
                  <Col xs={2} className="text-end">
                    <span className="threshold-readout">{value}</span>
                  </Col>
                </Row>
              ))}
            </Card.Body>
          </Card>
        </Col>

        <Col md={6} className="d-flex">
          <Card className="app-panel shadow-sm mb-3 flex-fill">
            <Card.Body className="p-3 d-flex flex-column">
              <h5 className="panel-heading">3D scene</h5>
              <div className="scene-frame mocap-scene-frame">
                <Canvas camera={{ position: [1.5, 1.5, 1.5], fov: 50 }}>
                  <ambientLight intensity={0.6} />
                  <directionalLight position={[5, 5, 5]} intensity={0.8} />
                  <axesHelper args={[0.5]} />
                  <gridHelper args={[2, 20]} />
                  {(cameraPoses.length > 0 ? cameraPoses : FALLBACK_CAMERA_POSES).map(
                    (p, i) => (
                      <CameraWireframe key={i} R={p.R} t={p.t} />
                    )
                  )}
                  {droneState.pos && (
                    <mesh position={[droneState.pos[0], droneState.pos[2], -droneState.pos[1]]}>
                      <sphereGeometry args={[0.015, 12, 12]} />
                      <meshStandardMaterial color="red" />
                    </mesh>
                  )}
                  <OrbitControls />
                  <Stats />
                </Canvas>
              </div>
            </Card.Body>
          </Card>
        </Col>
      </Row>

      <Row className="g-4">
        <Col md={4}>
          <Card className="app-panel shadow-sm mb-3">
            <Card.Body className="p-3">
              <h5 className="panel-heading">Flight</h5>
              <Row className="align-items-center mb-2 g-2">
                <Col xs="auto">
                  <button
                    type="button"
                    className={`btn ${droneArmed ? "btn-danger" : "btn-success"}`}
                    onClick={() => setDroneArmed(!droneArmed)}
                  >
                    {droneArmed ? "Disarm" : "Arm"}
                  </button>
                </Col>
                <Col xs="auto">
                  <button
                    type="button"
                    className="btn btn-primary"
                    onClick={sendTakeoff}
                    disabled={!droneArmed}
                  >
                    Takeoff
                  </button>
                </Col>
                <Col xs="auto">
                  <Form.Control
                    type="number"
                    step="0.05"
                    value={takeoffZ}
                    onChange={(e) => setTakeoffZ(e.target.value)}
                    style={{ width: 90 }}
                  />
                  <span className="ms-1">m</span>
                </Col>
                <Col xs="auto">
                  <button
                    type="button"
                    className="btn btn-warning"
                    onClick={sendLand}
                    disabled={!droneArmed}
                  >
                    Land
                  </button>
                </Col>
              </Row>

              <h6 className="section-subhead mt-2">Setpoint (m)</h6>
              <Row className="g-3">
                {(["x", "y", "z"] as const).map((axis, i) => (
                  <Col xs={4} key={axis}>
                    <Form.Label>{axis}</Form.Label>
                    <Form.Control
                      type="number"
                      step="0.05"
                      value={droneSetpoint[i]}
                      onChange={(e) => {
                        const next = droneSetpoint.slice();
                        next[i] = e.target.value;
                        setDroneSetpoint(next);
                      }}
                    />
                  </Col>
                ))}
              </Row>

              <h6 className="section-subhead mt-4">Trim (us)</h6>
              <Row className="g-3">
                {["T", "R", "P", "Y"].map((axis, i) => (
                  <Col xs={3} key={axis}>
                    <Form.Label>{axis}</Form.Label>
                    <Form.Control
                      type="number"
                      step="1"
                      value={droneTrim[i]}
                      onChange={(e) => {
                        const next = droneTrim.slice();
                        next[i] = e.target.value;
                        setDroneTrim(next);
                      }}
                    />
                  </Col>
                ))}
              </Row>
            </Card.Body>
          </Card>
        </Col>

        <Col md={5}>
          <Card className="app-panel shadow-sm mb-3">
            <Card.Body className="p-3">
              <h5 className="panel-heading">PID</h5>
              {PID_LABELS.map((label, i) => (
                <Row key={i} className="align-items-center mb-1 pid-row">
                  <Col xs={5}>
                    <small>{label}</small>
                  </Col>
                  <Col xs={5}>
                    <Form.Control
                      size="sm"
                      type="number"
                      step="0.01"
                      value={dronePID[i]}
                      onChange={(e) => {
                        const next = dronePID.slice();
                        next[i] = e.target.value;
                        setDronePID(next);
                      }}
                    />
                  </Col>
                </Row>
              ))}
            </Card.Body>
          </Card>
        </Col>

        <Col md={3}>
          <Card className="app-panel shadow-sm mb-3">
            <Card.Body className="p-3">
              <h5 className="panel-heading">Telemetry</h5>
              <div className="telemetry-line">
                <small>pos (m): {fmtArr(droneState.pos)}</small>
              </div>
              <div className="telemetry-line">
                <small>vel (m/s): {fmtArr(droneState.vel)}</small>
              </div>
              <div className="telemetry-line">
                <small>heading (rad): {fmt(droneState.heading)}</small>
              </div>
              <div className="telemetry-line">
                <small>state: {droneState.state}</small>
              </div>
              <hr />
              <div className="telemetry-subhead">
                <small>sticks (us):</small>
              </div>
              <div className="telemetry-line">
                <small>T {droneState.sticks?.[0] ?? "-"}</small>
              </div>
              <div className="telemetry-line">
                <small>R {droneState.sticks?.[1] ?? "-"}</small>
              </div>
              <div className="telemetry-line">
                <small>P {droneState.sticks?.[2] ?? "-"}</small>
              </div>
              <div className="telemetry-line">
                <small>Y {droneState.sticks?.[3] ?? "-"}</small>
              </div>
              <div className="telemetry-line">
                <small>A {droneState.sticks?.[4] ?? "-"}</small>
              </div>
            </Card.Body>
          </Card>
        </Col>
      </Row>
    </>
  );
}
