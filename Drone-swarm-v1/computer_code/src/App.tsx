"use client";

import { useEffect, useState } from "react";
import { Card, Col, Container, Form, Row } from "react-bootstrap";
import { Canvas } from "@react-three/fiber";
import { OrbitControls, Stats } from "@react-three/drei";

import CameraWireframe from "./components/CameraWireframe";
import { socket } from "./shared/styles/scripts/socket";

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

export default function App() {
  const [cameraStreamRunning, setCameraStreamRunning] = useState(false);
  const [threshold, setThreshold] = useState(180);

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
    <Container fluid className="app-shell">
      <Row className="app-header g-3 align-items-center">
        <Col md="auto" className="brand-block">
          <div className="brand-mark">
            <span>Drone Configurator</span>
          </div>
          <h2 className="app-title">MoCap single drone</h2>
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
      </Row>

      <Row className="g-4">
        <Col md={6}>
          <Card className="app-panel shadow-sm mb-3">
            <Card.Body className="p-3">
              <Row className="panel-heading align-items-center">
                <Col xs="auto">
                  <h5>Camera stream</h5>
                </Col>
                <Col className="panel-toolbar">
                  <button
                    type="button"
                    className={`btn btn-sm me-3 ${cameraStreamRunning ? "btn-outline-danger" : "btn-outline-primary"}`}
                    onClick={() => setCameraStreamRunning(!cameraStreamRunning)}
                  >
                    {cameraStreamRunning ? "Stop" : "Start"}
                  </button>
                  <Form.Range
                    min={0}
                    max={250}
                    value={threshold}
                    className="threshold-slider"
                    onChange={(e) => setThreshold(parseInt(e.target.value, 10))}
                  />
                  <span className="threshold-readout">threshold {threshold}</span>
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
            </Card.Body>
          </Card>
        </Col>

        <Col md={6}>
          <Card className="app-panel shadow-sm mb-3" style={{ minHeight: 420 }}>
            <Card.Body className="p-3">
              <h5 className="panel-heading">3D scene</h5>
              <div className="scene-frame" style={{ width: "100%", height: 380 }}>
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
    </Container>
  );
}
