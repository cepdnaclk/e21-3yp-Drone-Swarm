"use client";

import { useEffect, useRef, useState } from "react";
import { Card, Col, Form, Row } from "react-bootstrap";

import { socket } from "../shared/styles/scripts/socket";

type PortInfo = { device: string; description: string };

type HwConfig = {
  camera_indices?: number[];
  serial_port?: string;
  serial_open?: boolean;
  serial_ports?: PortInfo[];
};

type Ack = { ok?: boolean; error?: string };

export default function CameraSettingsView() {
  const [indices, setIndices] = useState<string[]>(["0", "1", "2", "3"]);
  const [indicesError, setIndicesError] = useState("");
  const [reloadStatus, setReloadStatus] =
    useState<"idle" | "reloading" | "done" | "error">("idle");
  const [reloadError, setReloadError] = useState("");
  // Don't clobber in-progress edits when another client broadcasts hw-config;
  // reset after a successful apply so the confirmed values flow back in.
  const indicesTouched = useRef(false);

  const [ports, setPorts] = useState<PortInfo[]>([]);
  const [currentPort, setCurrentPort] = useState("");
  const [serialOpen, setSerialOpen] = useState(false);
  const [selectedPort, setSelectedPort] = useState("");
  const [portStatus, setPortStatus] =
    useState<"idle" | "applying" | "ok" | "error">("idle");
  const [portError, setPortError] = useState("");
  const portTouched = useRef(false);

  useEffect(() => {
    const onHwConfig = (data: HwConfig) => {
      if (!data) return;
      if (Array.isArray(data.camera_indices) && !indicesTouched.current) {
        setIndices(data.camera_indices.map(String));
      }
      if (typeof data.serial_port === "string") {
        setCurrentPort(data.serial_port);
        if (!portTouched.current) setSelectedPort(data.serial_port);
      }
      if (typeof data.serial_open === "boolean") setSerialOpen(data.serial_open);
      if (Array.isArray(data.serial_ports)) setPorts(data.serial_ports);
    };

    const onCameraReload = (data: { status?: string; error?: string }) => {
      if (data?.status === "reloading") {
        setReloadStatus("reloading");
      } else if (data?.status === "done") {
        indicesTouched.current = false;
        setReloadStatus("done");
        window.setTimeout(() => setReloadStatus((s) => (s === "done" ? "idle" : s)), 2500);
      } else if (data?.status === "error") {
        setReloadStatus("error");
        setReloadError(data?.error ?? "camera reload failed");
      }
    };

    socket.on("hw-config", onHwConfig);
    socket.on("camera-reload", onCameraReload);
    socket.emit("get-hw-config", {}, onHwConfig);
    return () => {
      socket.off("hw-config", onHwConfig);
      socket.off("camera-reload", onCameraReload);
    };
  }, []);

  const refreshPorts = () => socket.emit("get-hw-config", {}, (data: HwConfig) => {
    if (Array.isArray(data?.serial_ports)) setPorts(data.serial_ports);
    if (typeof data?.serial_open === "boolean") setSerialOpen(data.serial_open);
  });

  const applyIndices = () => {
    const parsed = indices.map((v) => parseInt(v, 10));
    if (parsed.some((v) => !Number.isFinite(v) || v < 0)) {
      setIndicesError("Every index must be a whole number ≥ 0.");
      return;
    }
    if (new Set(parsed).size !== parsed.length) {
      setIndicesError("Indices must be unique.");
      return;
    }
    setIndicesError("");
    setReloadError("");
    setReloadStatus("reloading");
    socket.emit("set-camera-indices", { indices: parsed }, (res?: Ack) => {
      if (!res?.ok) {
        setReloadStatus("error");
        setReloadError(res?.error ?? "backend rejected the request");
      }
      // On ok the backend drives status via the "camera-reload" event.
    });
  };

  const applyPort = () => {
    if (!selectedPort) return;
    setPortStatus("applying");
    setPortError("");
    socket.emit("set-serial-port", { port: selectedPort }, (res?: Ack) => {
      if (res?.ok) {
        portTouched.current = false;
        setPortStatus("ok");
        window.setTimeout(() => setPortStatus((s) => (s === "ok" ? "idle" : s)), 2500);
      } else {
        setPortStatus("error");
        setPortError(res?.error ?? "backend rejected the request");
      }
    });
  };

  // Always offer the backend's current port even if the scan didn't list it
  // (e.g. the device is unplugged right now).
  const portOptions = ports.some((p) => p.device === currentPort) || !currentPort
    ? ports
    : [{ device: currentPort, description: "current (not detected)" }, ...ports];

  return (
    <>
      <Row className="app-header g-3 align-items-center">
        <Col md="auto" className="brand-block">
          <div className="brand-mark">
            <span>Hardware</span>
          </div>
          <h2 className="app-title">Camera settings</h2>
        </Col>
      </Row>

      <Row className="g-4">
        <Col md={6}>
          <Card className="app-panel shadow-sm mb-3">
            <Card.Body className="p-4">
              <h5 className="panel-heading">Camera indices</h5>
              <p className="text-muted">
                <small>
                  USB device index used for each tracker camera. Applying
                  releases all four captures and reopens them on the new
                  indices — takes a few seconds, the stream freezes meanwhile.
                </small>
              </p>
              <Row className="g-3">
                {indices.map((value, i) => (
                  <Col xs={3} key={i}>
                    <Form.Label>cam{i + 1}</Form.Label>
                    <Form.Control
                      type="number"
                      min={0}
                      step={1}
                      value={value}
                      disabled={reloadStatus === "reloading"}
                      onChange={(e) => {
                        indicesTouched.current = true;
                        const next = indices.slice();
                        next[i] = e.target.value;
                        setIndices(next);
                      }}
                    />
                  </Col>
                ))}
              </Row>
              <Row className="align-items-center mt-3 g-2">
                <Col xs="auto">
                  <button
                    type="button"
                    className="btn btn-primary"
                    onClick={applyIndices}
                    disabled={reloadStatus === "reloading"}
                  >
                    {reloadStatus === "reloading"
                      ? "Reloading cameras…"
                      : "Apply & reload cameras"}
                  </button>
                </Col>
                <Col>
                  {reloadStatus === "done" && (
                    <span className="text-success">Cameras reloaded.</span>
                  )}
                  {reloadStatus === "error" && (
                    <span className="text-danger">{reloadError}</span>
                  )}
                  {indicesError && (
                    <span className="text-danger">{indicesError}</span>
                  )}
                </Col>
              </Row>
            </Card.Body>
          </Card>
        </Col>

        <Col md={6}>
          <Card className="app-panel shadow-sm mb-3">
            <Card.Body className="p-4">
              <h5 className="panel-heading">Ground ESP serial link</h5>
              <p className="text-muted">
                <small>
                  COM port of the sender ESP32. Applying closes the current
                  link, reopens on the new port and re-syncs the sender (radio
                  target, PID, trims) — no backend restart needed.
                </small>
              </p>
              <div className="mb-3">
                <span className={`badge ${serialOpen ? "bg-success" : "bg-danger"}`}>
                  {serialOpen ? "Link open" : "Link closed"}
                </span>{" "}
                <small className="text-muted">current port: {currentPort || "—"}</small>
              </div>
              <Row className="align-items-end g-2">
                <Col>
                  <Form.Label>COM port</Form.Label>
                  <Form.Select
                    value={selectedPort}
                    disabled={portStatus === "applying"}
                    onChange={(e) => {
                      portTouched.current = true;
                      setSelectedPort(e.target.value);
                    }}
                  >
                    {!selectedPort && (
                      <option value="" disabled>
                        Select a port
                      </option>
                    )}
                    {portOptions.map((p) => (
                      <option key={p.device} value={p.device}>
                        {p.device} — {p.description}
                      </option>
                    ))}
                  </Form.Select>
                </Col>
                <Col xs="auto">
                  <button
                    type="button"
                    className="btn btn-outline-secondary"
                    onClick={refreshPorts}
                    disabled={portStatus === "applying"}
                  >
                    Refresh
                  </button>
                </Col>
                <Col xs="auto">
                  <button
                    type="button"
                    className="btn btn-primary"
                    onClick={applyPort}
                    disabled={!selectedPort || portStatus === "applying"}
                  >
                    {portStatus === "applying" ? "Connecting…" : "Apply"}
                  </button>
                </Col>
              </Row>
              <div className="mt-2">
                {portStatus === "ok" && (
                  <span className="text-success">Connected to {currentPort}.</span>
                )}
                {portStatus === "error" && (
                  <span className="text-danger">{portError}</span>
                )}
              </div>
            </Card.Body>
          </Card>
        </Col>
      </Row>

      <Row className="g-4">
        <Col>
          <Card className="app-panel shadow-sm">
            <Card.Body className="p-4">
              <h5 className="panel-heading">More camera tools</h5>
              <div className="empty-state">
                Additional camera features (per-camera preview, exposure,
                resolution) will live here in a later iteration.
              </div>
            </Card.Body>
          </Card>
        </Col>
      </Row>
    </>
  );
}
