"use client";

import { useEffect, useState } from "react";
import { Button, Card, Col, Container, Form, Row } from "react-bootstrap";
import { Canvas } from "@react-three/fiber";
import { OrbitControls, Stats } from "@react-three/drei";

import CameraWireframe from "./components/CameraWireframe";
import { socket } from "./shared/styles/scripts/socket";

// =====================================================================
// Single-drone mocap controller (PC-side flight loop lives in api/).
// Backend events:
//   "camera-pose"             -> { camera_poses: [{R, t}, ...] }   (on connect)
//   "to-world-coords-matrix"  -> { to_world_coords_matrix: 4x4 }   (on connect)
//   "drone-state" @ 30 Hz     -> { pos, vel, heading, heading_age,
//                                  sticks: [T,R,P,Y,A], state, fps,
//                                  tracker_fresh }
// Backend listens for:
//   "arm-drone" { armed: bool }
//   "takeoff"   { z: float }
//   "land"      {}
//   "set-drone-pid"      { dronePID: [17 floats] }
//   "set-drone-setpoint" { droneSetpoint: [x, y, z] }
//   "set-drone-trim"     { droneTrim: [t, r, p, y] }
//   "update-camera-settings" { threshold: int }
// =====================================================================

const PID_LABELS = [
  "Kp pos xy", "Ki pos xy", "Kd pos xy",
  "Kp pos z",  "Ki pos z",  "Kd pos z",
  "Kp yaw",    "Ki yaw",    "Kd yaw",
  "Kp vel xy", "Ki vel xy", "Kd vel xy",
  "Kp vel z",  "Ki vel z",  "Kd vel z",
  "ground eff coef",  // accepted but ignored on the PC side
  "ground eff offset",
];

const DEFAULT_PID = [
  "2.5", "0.0", "0.4",
  "3.5", "0.5", "0.5",
  "80",  "10",  "5",
  "8",   "1",   "0.3",
  "120", "40",  "20",
  "0",   "0",
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

export default function App() {
  // Camera stream
  const [cameraStreamRunning, setCameraStreamRunning] = useState(false);
  const [threshold, setThreshold] = useState(180);

  // Backend-provided scene calibration
  const [cameraPoses, setCameraPoses] = useState<{ R: number[][]; t: number[] }[]>([]);
  // toWorldCoordsMatrix is consumed by other tools but unused for rendering now
  // (camera_poses_in_world() already returns world-frame poses).
  const [, setToWorldCoordsMatrix] = useState<number[][] | null>(null);

  // Live drone telemetry from backend
  const [droneState, setDroneState] = useState<DroneState>({
    pos: null, vel: null, heading: null, heading_age: null,
    sticks: null, state: "IDLE", fps: 0, tracker_fresh: false,
  });

  // Outgoing commands
  const [droneArmed, setDroneArmed] = useState(false);
  const [takeoffZ, setTakeoffZ] = useState("0.20");
  const [dronePID, setDronePID] = useState<string[]>(DEFAULT_PID);
  const [droneSetpoint, setDroneSetpoint] = useState<string[]>(["0", "0", "0.20"]);
  const [droneTrim, setDroneTrim] = useState<string[]>(["0", "0", "0", "0"]);

  // ---------------- Sockets ----------------

  useEffect(() => {
    socket.on("camera-pose", (data) => {
      setCameraPoses(data["camera_poses"] ?? []);
    });
    socket.on("to-world-coords-matrix", (data) => {
      setToWorldCoordsMatrix(data["to_world_coords_matrix"] ?? null);
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

  // Arm/disarm: re-emit on a ping so PC failsafe stays alive (also re-emits the value)
  useEffect(() => {
    socket.emit("arm-drone", { armed: droneArmed });
    const id = setInterval(() => socket.emit("arm-drone", { armed: droneArmed }), 500);
    return () => clearInterval(id);
  }, [droneArmed]);

  useEffect(() => {
    socket.emit("set-drone-pid", { dronePID: dronePID.map((x) => parseFloat(x)) });
  }, [dronePID]);

  useEffect(() => {
    socket.emit("set-drone-trim", { droneTrim: droneTrim.map((x) => parseInt(x, 10)) });
  }, [droneTrim]);

  useEffect(() => {
    socket.emit("set-drone-setpoint", { droneSetpoint: droneSetpoint.map((x) => parseFloat(x)) });
  }, [droneSetpoint]);

  useEffect(() => {
    socket.emit("update-camera-settings", { threshold });
  }, [threshold]);

  // ---------------- Helpers ----------------

  const fmt = (x: number | null | undefined, digits = 3) =>
    x === null || x === undefined || Number.isNaN(x) ? "—" : x.toFixed(digits);

  const fmtArr = (xs: number[] | null | undefined, digits = 3) =>
    xs ? xs.map((x) => fmt(x, digits)).join(", ") : "—";

  const sendTakeoff = () => {
    const z = parseFloat(takeoffZ);
    if (Number.isFinite(z) && z > 0) socket.emit("takeoff", { z });
  };
  const sendLand = () => socket.emit("land", {});

  // ---------------- Render ----------------

  return (
    <Container fluid>
      <Row className="mt-3 mb-3" style={{ alignItems: "center" }}>
        <Col className="ms-4" md="auto">
          <h2>MoCap — single drone</h2>
        </Col>
        <Col>
          <span className="me-3">State: <b>{droneState.state}</b></span>
          <span className="me-3">FPS: {fmt(droneState.fps, 1)}</span>
          <span className="me-3">tracker: {droneState.tracker_fresh ? "✓" : "·"}</span>
          <span className="me-3">heading age: {fmt(droneState.heading_age, 2)} s</span>
        </Col>
      </Row>

      <Row>
        <Col md={6}>
          <Card className="shadow-sm p-3 mb-3">
            <Row>
              <Col xs="auto"><h5>Camera stream</h5></Col>
              <Col>
                <Button
                  size="sm"
                  className="me-3"
                  variant={cameraStreamRunning ? "outline-danger" : "outline-primary"}
                  onClick={() => setCameraStreamRunning(!cameraStreamRunning)}
                >
                  {cameraStreamRunning ? "Stop" : "Start"}
                </Button>
                <Form.Range
                  min={0} max={250} value={threshold}
                  style={{ width: 160, display: "inline-block", verticalAlign: "middle" }}
                  onChange={(e) => setThreshold(parseInt(e.target.value, 10))}
                />
                <span className="ms-2">threshold {threshold}</span>
              </Col>
            </Row>
            <Row className="mt-2" style={{ minHeight: 320 }}>
              <Col>
                {cameraStreamRunning && (
                  <img
                    src="http://localhost:3001/api/camera-stream"
                    style={{ maxWidth: "100%" }}
                    alt="camera stream"
                  />
                )}
              </Col>
            </Row>
          </Card>
        </Col>

        <Col md={6}>
          <Card className="shadow-sm p-3 mb-3" style={{ minHeight: 420 }}>
            <h5>3D scene</h5>
            <div style={{ width: "100%", height: 380 }}>
              <Canvas camera={{ position: [1.5, 1.5, 1.5], fov: 50 }}>
                <ambientLight intensity={0.6} />
                <directionalLight position={[5, 5, 5]} intensity={0.8} />
                <axesHelper args={[0.5]} />
                <gridHelper args={[2, 20]} />
                {cameraPoses.map((p, i) => (
                  <CameraWireframe key={i} R={p.R} t={p.t} />
                ))}
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
          </Card>
        </Col>
      </Row>

      <Row>
        <Col md={4}>
          <Card className="shadow-sm p-3 mb-3">
            <h5>Flight</h5>
            <Row className="align-items-center mb-2">
              <Col xs="auto">
                <Button
                  variant={droneArmed ? "danger" : "success"}
                  onClick={() => setDroneArmed(!droneArmed)}
                >
                  {droneArmed ? "Disarm" : "Arm"}
                </Button>
              </Col>
              <Col xs="auto">
                <Button variant="primary" onClick={sendTakeoff} disabled={!droneArmed}>
                  Takeoff
                </Button>
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
                <Button variant="warning" onClick={sendLand} disabled={!droneArmed}>
                  Land
                </Button>
              </Col>
            </Row>

            <h6 className="mt-2">Setpoint (m)</h6>
            <Row>
              {(["x", "y", "z"] as const).map((axis, i) => (
                <Col xs={4} key={axis}>
                  <Form.Label>{axis}</Form.Label>
                  <Form.Control
                    type="number" step="0.05"
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

            <h6 className="mt-3">Trim (µs)</h6>
            <Row>
              {["T", "R", "P", "Y"].map((axis, i) => (
                <Col xs={3} key={axis}>
                  <Form.Label>{axis}</Form.Label>
                  <Form.Control
                    type="number" step="1"
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
          </Card>
        </Col>

        <Col md={5}>
          <Card className="shadow-sm p-3 mb-3">
            <h5>PID</h5>
            {PID_LABELS.map((label, i) => (
              <Row key={i} className="align-items-center mb-1">
                <Col xs={5}><small>{label}</small></Col>
                <Col xs={5}>
                  <Form.Control
                    size="sm" type="number" step="0.01"
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
          </Card>
        </Col>

        <Col md={3}>
          <Card className="shadow-sm p-3 mb-3">
            <h5>Telemetry</h5>
            <div><small>pos (m): {fmtArr(droneState.pos)}</small></div>
            <div><small>vel (m/s): {fmtArr(droneState.vel)}</small></div>
            <div><small>heading (rad): {fmt(droneState.heading)}</small></div>
            <div><small>state: {droneState.state}</small></div>
            <hr />
            <div><small>sticks (µs):</small></div>
            <div><small>T {droneState.sticks?.[0] ?? "—"}</small></div>
            <div><small>R {droneState.sticks?.[1] ?? "—"}</small></div>
            <div><small>P {droneState.sticks?.[2] ?? "—"}</small></div>
            <div><small>Y {droneState.sticks?.[3] ?? "—"}</small></div>
            <div><small>A {droneState.sticks?.[4] ?? "—"}</small></div>
          </Card>
        </Col>
      </Row>
    </Container>
  );
}
