"use client";

// Calibration wizard: guides the user through the 4-camera pipeline
// (intrinsics -> extrinsics -> landmarks -> verify) against the backend's
// CalibrationManager. All session state lives on the backend and arrives via
// the "calibration-status" event, so a page refresh resumes cleanly.

import { useEffect, useRef, useState } from "react";
import { Card, Col, Form, Row } from "react-bootstrap";
import { Canvas } from "@react-three/fiber";
import { OrbitControls } from "@react-three/drei";

import CameraWireframe from "../components/CameraWireframe";
import { backendUrl } from "../config";
import { socket } from "../shared/styles/scripts/socket";

type StepId = "intrinsics" | "extrinsics" | "landmarks" | "verify";

type IntrinsicResult = {
  rms_error: number;
  fx: number;
  fy: number;
  cx: number;
  cy: number;
  distortion: number[];
  valid_images: number;
  total_images: number;
  image_size: number[];
  per_image: { name: string; ok: boolean }[];
};

type ExtrinsicResults = {
  sets_total: number;
  sets_valid: number;
  per_set: {
    set: number;
    valid: boolean;
    errors: Record<string, number | null>;
    distances_mm: Record<string, number>;
  }[];
  per_cam: Record<
    string,
    { t_mm: number[]; distance_from_cam1_mm: number; sets_used: number }
  >;
  pair_distances_mm: Record<string, number>;
};

type LandmarkPoint = { name: string; cam1: number[]; world: number[] };

type LandmarkResults = {
  scale: number;
  mean_error_mm: number;
  max_error_mm: number;
  per_landmark: {
    name: string;
    world_mm: number[];
    predicted_mm: number[];
    error_mm: number;
  }[];
};

type CalibStatus = {
  active: boolean;
  phase: "idle" | "starting" | "ready" | "applying";
  step: StepId | null;
  start_step: StepId | null;
  steps: StepId[];
  params: { checkerboard: number[]; square_size_mm: number };
  camera_indices: number[] | null;
  cameras_ok: boolean[];
  detect: boolean[];
  busy: string | null;
  error: string | null;
  last_event: "accepted" | "cancelled" | null;
  intrinsics: {
    active_cam: number;
    counts: number[];
    calibrated: boolean[];
    results: Record<string, IntrinsicResult | null>;
    min_images: number;
    recommended_images: number;
  };
  extrinsics: {
    sets: number;
    computed: boolean;
    results: ExtrinsicResults | null;
    min_sets: number;
    recommended_sets: number;
  };
  landmarks: {
    points: LandmarkPoint[];
    computed: boolean;
    results: LandmarkResults | null;
    live_cam1_mm: number[] | null;
    thresholds: number[];
    min_points: number;
    recommended_points: number;
  };
  verify: {
    live_cam1_mm: number[] | null;
    live_world_mm: number[] | null;
    live_world_m: number[] | null;
    camera_poses: { R: number[][]; t: number[] }[] | null;
    world_matrix: number[][] | null;
  };
  logs: Record<string, string[]>;
  current_info: {
    files: Record<string, string | null>;
    complete: boolean;
    newest: string | null;
    info: {
      accepted_at?: string;
      start_step?: string;
      params?: { checkerboard?: number[]; square_size_mm?: number };
      landmarks?: { mean_error_mm?: number; max_error_mm?: number; count?: number };
    } | null;
  };
};

const STEP_META: Record<StepId, { title: string; short: string }> = {
  intrinsics: { title: "Intrinsics", short: "Per-camera lens" },
  extrinsics: { title: "Extrinsics", short: "Camera positions" },
  landmarks: { title: "Landmarks", short: "World origin" },
  verify: { title: "Verify", short: "Test & accept" },
};

const STREAM_URL = backendUrl("/api/calibration-stream");

const fmt = (x: number | null | undefined, digits = 1) =>
  x === null || x === undefined || Number.isNaN(x) ? "-" : x.toFixed(digits);

export default function CalibrationView() {
  const [status, setStatus] = useState<CalibStatus | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  // ---- setup form (idle screen) ----
  const [cbCols, setCbCols] = useState("9");
  const [cbRows, setCbRows] = useState("6");
  const [squareSize, setSquareSize] = useState("23.9");
  const [startFrom, setStartFrom] = useState<StepId>("intrinsics");

  // ---- landmark form ----
  const [lmName, setLmName] = useState("A");
  const [lmWorld, setLmWorld] = useState<string[]>(["0", "0", "0"]);
  const [capturingLm, setCapturingLm] = useState(false);

  // ---- thresholds (local override so slider drags don't fight status pushes) ----
  const [thresholdOverride, setThresholdOverride] = useState<number[] | null>(null);

  // ---- restart / confirm dialogs ----
  const [restartStep, setRestartStep] = useState<StepId>("intrinsics");
  const [restartCam, setRestartCam] = useState<string>("all");
  const [confirm, setConfirm] = useState<null | {
    title: string;
    body: string;
    label: string;
    variant: string;
    action: () => void;
  }>(null);

  const wrapperRef = useRef<HTMLDivElement>(null);
  const logRef = useRef<HTMLDivElement>(null);

  const act = (event: string, payload: Record<string, unknown> = {}) => {
    socket.emit(event, payload, (res?: { ok?: boolean; error?: string }) => {
      if (res && res.ok === false) {
        setActionError(res.error ?? "action failed");
        window.setTimeout(() => setActionError(null), 6000);
      }
    });
  };

  useEffect(() => {
    const onStatus = (s: CalibStatus) => setStatus(s);
    socket.on("calibration-status", onStatus);
    socket.emit("calibration-get-status", {}, (s?: CalibStatus) => {
      if (s && typeof s.active === "boolean") setStatus(s);
    });
    return () => {
      socket.off("calibration-status", onStatus);
    };
  }, []);

  // Reset per-session local state when the session ends.
  useEffect(() => {
    if (!status?.active) {
      setThresholdOverride(null);
      setCapturingLm(false);
    }
  }, [status?.active]);

  // Keep the restart selector within the legal range.
  useEffect(() => {
    if (!status?.active || !status.step || !status.start_step) return;
    const steps = status.steps;
    const lo = steps.indexOf(status.start_step);
    const hi = steps.indexOf(status.step);
    const cur = steps.indexOf(restartStep);
    if (cur < lo || cur > hi) setRestartStep(status.step);
  }, [status?.step, status?.start_step, status?.active]); // eslint-disable-line react-hooks/exhaustive-deps

  // Suggest the next free landmark name.
  const points = status?.landmarks.points ?? [];
  useEffect(() => {
    const used = new Set(points.map((p) => p.name));
    for (let i = 0; i < 26; i++) {
      const c = String.fromCharCode(65 + i);
      if (!used.has(c)) {
        setLmName(c);
        return;
      }
    }
    setLmName(`P${points.length + 1}`);
  }, [points.length]); // eslint-disable-line react-hooks/exhaustive-deps

  // Space = capture on the two capture steps (only while this section is visible).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.code !== "Space" || e.repeat) return;
      const el = wrapperRef.current;
      if (!el || el.offsetParent === null) return; // section hidden
      const target = e.target as HTMLElement | null;
      if (target && ["INPUT", "TEXTAREA", "SELECT", "BUTTON"].includes(target.tagName)) return;
      if (!status?.active || status.phase !== "ready" || status.busy) return;
      if (status.step !== "intrinsics" && status.step !== "extrinsics") return;
      e.preventDefault();
      act("calibration-capture");
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [status?.active, status?.phase, status?.busy, status?.step]); // eslint-disable-line react-hooks/exhaustive-deps

  // Auto-scroll the log console.
  const currentLog = status?.step ? status.logs[status.step] ?? [] : [];
  useEffect(() => {
    logRef.current?.scrollTo(0, logRef.current.scrollHeight);
  }, [currentLog.length]);

  const stepIndex = (s: StepId | null) => (s ? (status?.steps ?? []).indexOf(s) : -1);

  const captureLandmark = () => {
    const world = lmWorld.map((v) => parseFloat(v));
    if (world.some((v) => !Number.isFinite(v))) {
      setActionError("world coordinates must be numbers (mm)");
      window.setTimeout(() => setActionError(null), 6000);
      return;
    }
    setCapturingLm(true);
    socket.emit(
      "calibration-capture-landmark",
      { name: lmName.trim(), world },
      (res?: { ok?: boolean; error?: string }) => {
        setCapturingLm(false);
        if (res && res.ok === false) {
          setActionError(res.error ?? "capture failed");
          window.setTimeout(() => setActionError(null), 6000);
        }
      },
    );
  };

  const effectiveThresholds =
    thresholdOverride ?? status?.landmarks.thresholds ?? [180, 180, 180, 180];

  const setThreshold = (i: number, value: number) => {
    const next = effectiveThresholds.slice();
    next[i] = value;
    setThresholdOverride(next);
    act("calibration-set-thresholds", { thresholds: next });
  };

  // ------------------------------------------------------------------
  // Render helpers
  // ------------------------------------------------------------------

  const renderStepper = () => {
    if (!status?.active) return null;
    const startIdx = stepIndex(status.start_step);
    const curIdx = stepIndex(status.step);
    return (
      <div className="calib-stepper">
        {status.steps.map((s, i) => {
          const reused = i < startIdx;
          const done = i >= startIdx && i < curIdx;
          const current = i === curIdx;
          const cls = current ? "is-current" : done ? "is-done" : reused ? "is-reused" : "";
          return (
            <div key={s} className={`calib-step ${cls}`}>
              <span className="calib-step-index">{done ? "✓" : i + 1}</span>
              <span>
                <span className="calib-step-label">{STEP_META[s].title}</span>
                <span className="calib-step-sub">
                  {reused ? "from current calibration" : STEP_META[s].short}
                </span>
              </span>
            </div>
          );
        })}
      </div>
    );
  };

  const renderIdle = () => {
    const info = status?.current_info;
    const files = info?.files ?? {};
    const intrOk = [1, 2, 3, 4].filter((n) => files[`camera_${n}_params_new.json`]).length;
    const extOk = [2, 3, 4].filter((n) => files[`cam${n}_relative_to_cam1.npz`]).length;
    const worldOk = Boolean(files["cam1_to_world_transform.npz"]);
    const meta = info?.info;

    const startBlocked =
      (startFrom === "extrinsics" && intrOk < 4) ||
      (startFrom === "landmarks" && (intrOk < 4 || extOk < 3));

    return (
      <Row className="g-4">
        <Col lg={5}>
          <Card className="app-panel shadow-sm mb-3">
            <Card.Body className="p-4">
              <h5 className="panel-heading">Current calibration</h5>
              <table className="table table-dark table-sm table-borderless calib-table mb-2">
                <tbody>
                  <tr>
                    <td>Intrinsics (per-camera lens)</td>
                    <td className={intrOk === 4 ? "text-success" : "text-danger"}>
                      {intrOk}/4 cameras
                    </td>
                  </tr>
                  <tr>
                    <td>Extrinsics (relative to cam 1)</td>
                    <td className={extOk === 3 ? "text-success" : "text-danger"}>
                      {extOk}/3 cameras
                    </td>
                  </tr>
                  <tr>
                    <td>World transform</td>
                    <td className={worldOk ? "text-success" : "text-danger"}>
                      {worldOk ? "present" : "missing"}
                    </td>
                  </tr>
                  <tr>
                    <td>Last file change</td>
                    <td>{info?.newest ?? "-"}</td>
                  </tr>
                  {meta?.accepted_at && (
                    <tr>
                      <td>Last accepted via wizard</td>
                      <td>{meta.accepted_at.replace("T", " ")}</td>
                    </tr>
                  )}
                  {meta?.landmarks && (
                    <tr>
                      <td>Landmark fit error</td>
                      <td>
                        mean {fmt(meta.landmarks.mean_error_mm)} mm · max{" "}
                        {fmt(meta.landmarks.max_error_mm)} mm
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
              <div className="text-muted" style={{ fontSize: "0.8rem" }}>
                Accepting a new calibration keeps the outgoing set in{" "}
                <span className="mono">calibration_backup/</span>.
              </div>
            </Card.Body>
          </Card>

          <Card className="app-panel shadow-sm mb-3">
            <Card.Body className="p-4">
              <h5 className="panel-heading">How it works</h5>
              <ol className="text-muted" style={{ fontSize: "0.86rem", paddingLeft: "1.1rem" }}>
                <li className="mb-1">
                  <b>Intrinsics</b> — each camera learns its lens (focal length +
                  distortion) from checkerboard photos.
                </li>
                <li className="mb-1">
                  <b>Extrinsics</b> — all 4 cameras see the same board at once to
                  solve where they sit relative to camera 1.
                </li>
                <li className="mb-1">
                  <b>Landmarks</b> — the tracking LED is placed at measured room
                  positions to anchor camera-1 space to your world origin.
                </li>
                <li>
                  <b>Verify</b> — live 3D view on the new calibration; only your
                  Accept overwrites the current files.
                </li>
              </ol>
              <div className="text-muted" style={{ fontSize: "0.8rem" }}>
                Starting from a later step reuses earlier results from the current
                calibration. Everything after your starting point must be redone —
                changing one stage invalidates the stages built on top of it.
              </div>
            </Card.Body>
          </Card>
        </Col>

        <Col lg={7}>
          <Card className="app-panel shadow-sm mb-3">
            <Card.Body className="p-4">
              <h5 className="panel-heading">Start a calibration session</h5>

              <div className="calib-warn mb-3">
                Starting halts tracking and all flight commands until you accept or
                cancel. The drone must be idle on the ground.
              </div>

              <h6 className="section-subhead">Checkerboard</h6>
              <Row className="g-3 mb-2">
                <Col xs={4} sm={3}>
                  <Form.Label>Inner corners X</Form.Label>
                  <Form.Control
                    type="number"
                    min={2}
                    max={30}
                    value={cbCols}
                    onChange={(e) => setCbCols(e.target.value)}
                  />
                </Col>
                <Col xs={4} sm={3}>
                  <Form.Label>Inner corners Y</Form.Label>
                  <Form.Control
                    type="number"
                    min={2}
                    max={30}
                    value={cbRows}
                    onChange={(e) => setCbRows(e.target.value)}
                  />
                </Col>
                <Col xs={4} sm={3}>
                  <Form.Label>Square size (mm)</Form.Label>
                  <Form.Control
                    type="number"
                    step="0.1"
                    value={squareSize}
                    onChange={(e) => setSquareSize(e.target.value)}
                  />
                </Col>
              </Row>
              <div className="text-muted mb-3" style={{ fontSize: "0.8rem" }}>
                Count INNER corners, not squares: a board with 10×7 squares has 9×6
                inner corners. Measure one square edge-to-edge — this sets the
                real-world scale of the whole system.
              </div>

              <h6 className="section-subhead">Start from</h6>
              {(
                [
                  {
                    id: "intrinsics" as StepId,
                    title: "Full calibration",
                    desc: "New cameras or lenses. Runs every step (~45–60 min).",
                  },
                  {
                    id: "extrinsics" as StepId,
                    title: "Extrinsics onward",
                    desc: "Cameras were moved but lenses unchanged. Reuses current intrinsics (~15–25 min).",
                  },
                  {
                    id: "landmarks" as StepId,
                    title: "Landmarks only",
                    desc: "Cameras untouched, but the world origin / room markings changed. Reuses current intrinsics + extrinsics (~10 min).",
                  },
                ] as { id: StepId; title: string; desc: string }[]
              ).map((opt) => (
                <label
                  key={opt.id}
                  className={`calib-start-option ${startFrom === opt.id ? "is-selected" : ""}`}
                >
                  <Form.Check
                    type="radio"
                    name="calib-start-from"
                    checked={startFrom === opt.id}
                    onChange={() => setStartFrom(opt.id)}
                    label={<span className="opt-title">{opt.title}</span>}
                  />
                  <span className="opt-desc">{opt.desc}</span>
                </label>
              ))}
              {startBlocked && (
                <div className="form-error mb-2">
                  The current calibration is missing files this starting point needs —
                  pick an earlier starting step.
                </div>
              )}

              <div className="d-flex align-items-center gap-3 mt-3">
                <button
                  type="button"
                  className="btn btn-primary"
                  disabled={startBlocked}
                  onClick={() =>
                    act("calibration-start", {
                      start_from: startFrom,
                      checkerboard: [parseInt(cbCols, 10), parseInt(cbRows, 10)],
                      square_size_mm: parseFloat(squareSize),
                    })
                  }
                >
                  Start session
                </button>
                {status?.last_event === "accepted" && (
                  <span className="text-success">
                    New calibration accepted and now in use.
                  </span>
                )}
                {status?.last_event === "cancelled" && (
                  <span className="text-muted">
                    Session cancelled — current calibration untouched.
                  </span>
                )}
              </div>
            </Card.Body>
          </Card>
        </Col>
      </Row>
    );
  };

  // ---- step panels ------------------------------------------------------

  const renderIntrinsics = () => {
    if (!status) return null;
    const s = status.intrinsics;
    const cam = s.active_cam;
    const count = s.counts[cam - 1] ?? 0;
    const detected = status.detect[cam - 1];
    const result = s.results[String(cam)];
    return (
      <>
        <div className="d-flex flex-wrap gap-2 mb-3">
          {[1, 2, 3, 4].map((n) => (
            <button
              key={n}
              type="button"
              className={`calib-cam-tab ${n === cam ? "is-active" : ""}`}
              onClick={() => act("calibration-set-active-camera", { cam: n })}
            >
              <span>
                Cam {n} {s.calibrated[n - 1] ? "✓" : ""}
              </span>
              <span className="cam-count">{s.counts[n - 1]} imgs</span>
            </button>
          ))}
        </div>

        <div className="d-flex flex-wrap align-items-center gap-2 mb-2">
          <span className={`detect-badge ${detected ? "is-on" : "is-off"}`}>
            {detected ? "checkerboard detected" : "no checkerboard"}
          </span>
          <span className="text-muted" style={{ fontSize: "0.8rem" }}>
            {count} captured · min {s.min_images}, aim for {s.recommended_images}+
          </span>
        </div>

        <div className="d-flex flex-wrap gap-2">
          <button
            type="button"
            className="btn btn-primary"
            disabled={status.busy !== null}
            onClick={() => act("calibration-capture")}
          >
            Capture image (Space)
          </button>
          <button
            type="button"
            className="btn btn-success"
            disabled={status.busy !== null || count < s.min_images}
            onClick={() => act("calibration-compute")}
          >
            {status.busy && status.busy.includes("calibrating")
              ? `${status.busy}…`
              : `Calibrate camera ${cam}`}
          </button>
          <button
            type="button"
            className="btn btn-outline-danger"
            disabled={status.busy !== null || count === 0}
            onClick={() =>
              setConfirm({
                title: `Redo camera ${cam} intrinsics`,
                body: `Delete camera ${cam}'s captured images and calibration? Other cameras keep theirs. Later steps are cleared too.`,
                label: "Redo camera",
                variant: "danger",
                action: () => act("calibration-restart", { step: "intrinsics", cam }),
              })
            }
          >
            Redo cam {cam}
          </button>
        </div>

        {result && (
          <table className="table table-dark table-sm table-borderless calib-table mt-3 mb-0">
            <tbody>
              <tr>
                <td>Reprojection RMS</td>
                <td className={result.rms_error < 1.0 ? "text-success" : "text-warning"}>
                  {fmt(result.rms_error, 4)} px{" "}
                  {result.rms_error < 1.0 ? "(good)" : "(high — consider redoing)"}
                </td>
              </tr>
              <tr>
                <td>Focal length fx / fy</td>
                <td>
                  {fmt(result.fx)} / {fmt(result.fy)}
                </td>
              </tr>
              <tr>
                <td>Principal point cx / cy</td>
                <td>
                  {fmt(result.cx)} / {fmt(result.cy)}
                </td>
              </tr>
              <tr>
                <td>Images used</td>
                <td>
                  {result.valid_images} of {result.total_images}
                </td>
              </tr>
            </tbody>
          </table>
        )}
      </>
    );
  };

  const renderExtrinsics = () => {
    if (!status) return null;
    const s = status.extrinsics;
    const allDetected = status.detect.every(Boolean);
    return (
      <>
        <div className="d-flex flex-wrap gap-2 mb-2">
          {[1, 2, 3, 4].map((n) => (
            <span
              key={n}
              className={`detect-badge ${status.detect[n - 1] ? "is-on" : "is-off"}`}
            >
              cam {n}
            </span>
          ))}
        </div>
        <div className="text-muted mb-2" style={{ fontSize: "0.8rem" }}>
          {s.sets} sets captured · min {s.min_sets}, aim for {s.recommended_sets}+
        </div>
        <div className="d-flex flex-wrap gap-2">
          <button
            type="button"
            className="btn btn-primary"
            disabled={status.busy !== null || !allDetected}
            onClick={() => act("calibration-capture")}
          >
            Capture set (Space)
          </button>
          <button
            type="button"
            className="btn btn-success"
            disabled={status.busy !== null || s.sets < s.min_sets}
            onClick={() => act("calibration-compute")}
          >
            {status.busy === "computing relative extrinsics"
              ? `${status.busy}…`
              : "Compute relative extrinsics"}
          </button>
        </div>
        {!allDetected && (
          <div className="text-muted mt-2" style={{ fontSize: "0.8rem" }}>
            Capture unlocks when all four cameras see the board at the same time.
          </div>
        )}

        {s.results && (
          <>
            <h6 className="section-subhead mt-3">
              Camera positions ({s.results.sets_valid}/{s.results.sets_total} sets valid)
            </h6>
            <table className="table table-dark table-sm table-borderless calib-table mb-1">
              <thead>
                <tr>
                  <th>Pair</th>
                  <th>Distance</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(s.results.pair_distances_mm).map(([pair, d]) => (
                  <tr key={pair}>
                    <td>{pair}</td>
                    <td>
                      {fmt(d)} mm ({fmt(d / 1000, 2)} m)
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="text-muted" style={{ fontSize: "0.8rem" }}>
              Sanity-check these against a tape measure before continuing.
            </div>
          </>
        )}
      </>
    );
  };

  const renderLandmarks = () => {
    if (!status) return null;
    const s = status.landmarks;
    const live = s.live_cam1_mm;
    return (
      <>
        <div className={`calib-readout mb-3 ${live ? "is-live" : "is-dead"}`}>
          {live
            ? `LED in cam1 frame:  X ${fmt(live[0], 0)}  Y ${fmt(live[1], 0)}  Z ${fmt(live[2], 0)}  mm`
            : "LED not seen by at least 2 cameras"}
        </div>

        <h6 className="section-subhead">LED thresholds</h6>
        {effectiveThresholds.map((value, i) => (
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
                onChange={(e) => setThreshold(i, parseInt(e.target.value, 10))}
              />
            </Col>
            <Col xs={2} className="text-end">
              <span className="threshold-readout">{value}</span>
            </Col>
          </Row>
        ))}

        <h6 className="section-subhead mt-3">Capture a landmark</h6>
        <Row className="g-2 align-items-end mb-2">
          <Col xs={3} sm={2}>
            <Form.Label>Name</Form.Label>
            <Form.Control value={lmName} onChange={(e) => setLmName(e.target.value)} />
          </Col>
          {(["X", "Y", "Z"] as const).map((axis, i) => (
            <Col xs={3} sm={2} key={axis}>
              <Form.Label>World {axis} (mm)</Form.Label>
              <Form.Control
                type="number"
                step="10"
                value={lmWorld[i]}
                onChange={(e) => {
                  const next = lmWorld.slice();
                  next[i] = e.target.value;
                  setLmWorld(next);
                }}
              />
            </Col>
          ))}
          <Col xs="auto">
            <button
              type="button"
              className="btn btn-primary"
              disabled={status.busy !== null || capturingLm || !live}
              onClick={captureLandmark}
            >
              {capturingLm ? "Sampling…" : "Capture landmark"}
            </button>
          </Col>
        </Row>

        {s.points.length > 0 && (
          <table className="table table-dark table-sm table-borderless calib-table mb-2">
            <thead>
              <tr>
                <th>Name</th>
                <th>cam1 (mm)</th>
                <th>world (mm)</th>
                {s.results ? <th>error</th> : null}
                <th />
              </tr>
            </thead>
            <tbody>
              {s.points.map((p) => {
                const err = s.results?.per_landmark.find((e) => e.name === p.name);
                return (
                  <tr key={p.name}>
                    <td>{p.name}</td>
                    <td className="mono">{p.cam1.map((v) => fmt(v, 0)).join(", ")}</td>
                    <td className="mono">{p.world.map((v) => fmt(v, 0)).join(", ")}</td>
                    {s.results ? (
                      <td className={err && err.error_mm > 50 ? "text-warning" : ""}>
                        {err ? `${fmt(err.error_mm)} mm` : "-"}
                      </td>
                    ) : null}
                    <td>
                      <button
                        type="button"
                        className="btn btn-sm btn-outline-danger"
                        disabled={status.busy !== null}
                        onClick={() => act("calibration-delete-landmark", { name: p.name })}
                      >
                        remove
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}

        <div className="d-flex flex-wrap align-items-center gap-3">
          <button
            type="button"
            className="btn btn-success"
            disabled={status.busy !== null || s.points.length < s.min_points}
            onClick={() => act("calibration-compute")}
          >
            {status.busy === "computing world transform"
              ? `${status.busy}…`
              : "Compute world transform"}
          </button>
          <span className="text-muted" style={{ fontSize: "0.8rem" }}>
            {s.points.length} landmarks · min {s.min_points}, aim for{" "}
            {s.recommended_points}+ spread across the floor
          </span>
        </div>

        {s.results && (
          <table className="table table-dark table-sm table-borderless calib-table mt-3 mb-0">
            <tbody>
              <tr>
                <td>Scale</td>
                <td>{fmt(s.results.scale, 5)}</td>
              </tr>
              <tr>
                <td>Mean landmark error</td>
                <td className={s.results.mean_error_mm < 50 ? "text-success" : "text-warning"}>
                  {fmt(s.results.mean_error_mm)} mm
                </td>
              </tr>
              <tr>
                <td>Max landmark error</td>
                <td className={s.results.max_error_mm < 80 ? "text-success" : "text-warning"}>
                  {fmt(s.results.max_error_mm)} mm
                </td>
              </tr>
            </tbody>
          </table>
        )}
      </>
    );
  };

  const renderVerify = () => {
    if (!status) return null;
    const v = status.verify;
    const liveM = v.live_world_m;
    const poses = v.camera_poses ?? [];
    return (
      <>
        <div className={`calib-readout mb-2 ${liveM ? "is-live" : "is-dead"}`}>
          {liveM
            ? `WORLD:  X ${fmt(liveM[0], 3)}  Y ${fmt(liveM[1], 3)}  Z ${fmt(liveM[2], 3)}  m`
            : "LED not seen by at least 2 cameras"}
        </div>
        {v.live_world_mm && (
          <div className="text-muted mb-2 mono" style={{ fontSize: "0.8rem" }}>
            = ({v.live_world_mm.map((x) => fmt(x, 0)).join(", ")}) mm · cam1 (
            {(v.live_cam1_mm ?? []).map((x) => fmt(x, 0)).join(", ")}) mm
          </div>
        )}

        <div className="scene-frame calib-scene-frame mb-3">
          <Canvas camera={{ position: [1.5, 1.5, 1.5], fov: 50 }}>
            <ambientLight intensity={0.6} />
            <directionalLight position={[5, 5, 5]} intensity={0.8} />
            <axesHelper args={[0.5]} />
            <gridHelper args={[2, 20]} />
            {poses.map((p, i) => (
              <CameraWireframe key={i} R={p.R} t={p.t} />
            ))}
            {status.landmarks.points.map((p) => (
              <mesh
                key={p.name}
                position={[p.world[0] / 1000, p.world[2] / 1000, -p.world[1] / 1000]}
              >
                <sphereGeometry args={[0.012, 12, 12]} />
                <meshStandardMaterial color="#4da3ff" />
              </mesh>
            ))}
            {liveM && (
              <mesh position={[liveM[0], liveM[2], -liveM[1]]}>
                <sphereGeometry args={[0.018, 12, 12]} />
                <meshStandardMaterial color="red" />
              </mesh>
            )}
            <OrbitControls />
          </Canvas>
        </div>
        <div className="text-muted mb-3" style={{ fontSize: "0.8rem" }}>
          Blue spheres = your landmarks · red = live LED · pyramids = staged camera
          poses. Drag to orbit.
        </div>

        <div className="d-flex flex-wrap gap-2">
          <button
            type="button"
            className="btn btn-success"
            disabled={status.busy !== null}
            onClick={() =>
              setConfirm({
                title: "Accept new calibration",
                body: "Overwrite the current calibration with this session's results? The outgoing set is kept in calibration_backup/ and the tracker restarts on the new files.",
                label: "Accept & apply",
                variant: "success",
                action: () => act("calibration-accept"),
              })
            }
          >
            Accept &amp; apply
          </button>
          <button
            type="button"
            className="btn btn-outline-danger"
            onClick={() =>
              setConfirm({
                title: "Cancel calibration",
                body: "Discard everything from this session? The current calibration stays untouched.",
                label: "Discard session",
                variant: "danger",
                action: () => act("calibration-cancel"),
              })
            }
          >
            Cancel session
          </button>
        </div>
      </>
    );
  };

  const INSTRUCTIONS: Record<StepId, JSX.Element> = {
    intrinsics: (
      <>
        <p className="mb-2">
          Each camera learns its lens parameters from checkerboard photos. Work
          through the cameras one at a time using the tabs.
        </p>
        <ul className="mb-2" style={{ paddingLeft: "1.1rem" }}>
          <li>Keep the board flat and well lit; avoid glare and motion blur.</li>
          <li>
            Cover the WHOLE image: corners, edges, near and far, and tilt the board
            up to ~45° in different directions.
          </li>
          <li>Hold still, wait for the green badge, then capture.</li>
          <li>
            Capture 15–25 images, then hit <b>Calibrate</b>. RMS under ~1 px is
            good; redo the camera if it's much higher.
          </li>
        </ul>
        <p className="mb-0 text-muted">The live view shows the selected camera only.</p>
      </>
    ),
    extrinsics: (
      <>
        <p className="mb-2">
          Now the cameras find each other. Every capture stores a synchronized
          4-camera snapshot of the same board.
        </p>
        <ul className="mb-2" style={{ paddingLeft: "1.1rem" }}>
          <li>
            Place or hold the board so ALL four cameras see it fully — capture
            unlocks only when all badges are green.
          </li>
          <li>
            Take {status?.extrinsics.recommended_sets ?? 10}+ sets at different
            positions, heights and tilts spread across the tracking volume.
          </li>
          <li>
            Then <b>Compute</b> and sanity-check the camera-to-camera distances
            against reality.
          </li>
        </ul>
        <p className="mb-0 text-warning">
          Do not move any camera after this step — that invalidates everything.
        </p>
      </>
    ),
    landmarks: (
      <>
        <p className="mb-2">
          Anchor the system to your room. Mark a few positions on the floor and
          measure their coordinates (mm) from your chosen origin: X, Y along the
          floor, Z up.
        </p>
        <ul className="mb-2" style={{ paddingLeft: "1.1rem" }}>
          <li>Turn on the drone's tracking LED (or a bare bright LED).</li>
          <li>Tune the thresholds until only the LED is detected.</li>
          <li>
            For each landmark: type its measured world coordinates, hold the LED
            still on the mark, and <b>Capture</b> (it averages ~1 s of fixes).
          </li>
          <li>
            Use {status?.landmarks.recommended_points ?? 5}+ points spread wide
            apart; include your origin (0, 0, 0). Points at different heights
            improve the Z axis.
          </li>
        </ul>
        <p className="mb-0 text-muted">
          Landmark errors after Compute show how well the world frame fits.
        </p>
      </>
    ),
    verify: (
      <>
        <p className="mb-2">
          The live position now uses ONLY this session's staged calibration —
          nothing has been overwritten yet.
        </p>
        <ul className="mb-2" style={{ paddingLeft: "1.1rem" }}>
          <li>
            Move the LED to known spots (your landmarks, tape measurements) and
            compare the readout.
          </li>
          <li>Check the camera wireframes sit where the cameras really are.</li>
          <li>
            Happy? <b>Accept &amp; apply</b>. Not happy? Restart from an earlier
            step or cancel — the current calibration is untouched either way.
          </li>
        </ul>
      </>
    ),
  };

  const renderActive = () => {
    if (!status || !status.step) return null;
    const step = status.step;
    const startIdx = stepIndex(status.start_step);
    const curIdx = stepIndex(step);
    const restartable = status.steps.slice(startIdx, curIdx + 1);

    const canNext =
      step === "intrinsics"
        ? status.intrinsics.calibrated.every(Boolean)
        : step === "extrinsics"
        ? status.extrinsics.computed
        : step === "landmarks"
        ? status.landmarks.computed
        : false;

    return (
      <>
        {renderStepper()}

        {status.phase === "starting" && (
          <div className="calib-warn mb-3">
            Opening cameras {(status.camera_indices ?? []).map(String).join(", ")}
            &hellip; this takes a few seconds.
          </div>
        )}
        {status.error && <div className="calib-error mb-3">{status.error}</div>}

        <Row className="g-4">
          <Col lg={7}>
            <Card className="app-panel shadow-sm mb-3">
              <Card.Body className="p-3">
                <Row className="panel-heading align-items-center">
                  <Col xs="auto">
                    <h5>
                      {STEP_META[step].title}
                      {status.busy ? ` — ${status.busy}…` : ""}
                    </h5>
                  </Col>
                  <Col className="panel-toolbar">
                    <span className="text-muted" style={{ fontSize: "0.78rem" }}>
                      cameras {status.cameras_ok.filter(Boolean).length}/4 ok
                    </span>
                  </Col>
                </Row>

                <img
                  src={STREAM_URL}
                  className="camera-frame calib-stream mb-3"
                  alt="calibration live view"
                />

                {step === "intrinsics" && renderIntrinsics()}
                {step === "extrinsics" && renderExtrinsics()}
                {step === "landmarks" && renderLandmarks()}
                {step === "verify" && renderVerify()}

                <hr />
                <div className="d-flex flex-wrap align-items-center gap-2">
                  {step !== "verify" && (
                    <button
                      type="button"
                      className="btn btn-primary"
                      disabled={!canNext || status.busy !== null}
                      onClick={() => act("calibration-next")}
                    >
                      Next step &rarr;
                    </button>
                  )}
                  <div className="d-flex align-items-center gap-2 ms-auto">
                    <Form.Select
                      size="sm"
                      style={{ width: 170 }}
                      value={restartStep}
                      onChange={(e) => setRestartStep(e.target.value as StepId)}
                    >
                      {restartable.map((s) => (
                        <option key={s} value={s}>
                          {STEP_META[s].title}
                        </option>
                      ))}
                    </Form.Select>
                    {restartStep === "intrinsics" && (
                      <Form.Select
                        size="sm"
                        style={{ width: 110 }}
                        value={restartCam}
                        onChange={(e) => setRestartCam(e.target.value)}
                      >
                        <option value="all">all cams</option>
                        {[1, 2, 3, 4].map((n) => (
                          <option key={n} value={String(n)}>
                            cam {n}
                          </option>
                        ))}
                      </Form.Select>
                    )}
                    <button
                      type="button"
                      className="btn btn-sm btn-outline-danger"
                      disabled={status.busy !== null}
                      onClick={() =>
                        setConfirm({
                          title: `Restart from ${STEP_META[restartStep].title}`,
                          body:
                            `This clears the staged results of ${STEP_META[restartStep].title}` +
                            (restartStep === "intrinsics" && restartCam !== "all"
                              ? ` (camera ${restartCam} only)`
                              : "") +
                            " and every step after it. You'll redo them from there.",
                          label: "Restart",
                          variant: "danger",
                          action: () =>
                            act("calibration-restart", {
                              step: restartStep,
                              cam:
                                restartStep === "intrinsics" && restartCam !== "all"
                                  ? parseInt(restartCam, 10)
                                  : null,
                            }),
                        })
                      }
                    >
                      Restart from&hellip;
                    </button>
                  </div>
                </div>
              </Card.Body>
            </Card>
          </Col>

          <Col lg={5}>
            <Card className="app-panel shadow-sm mb-3">
              <Card.Body className="p-3">
                <h5 className="panel-heading">Instructions</h5>
                <div style={{ fontSize: "0.88rem" }}>{INSTRUCTIONS[step]}</div>
              </Card.Body>
            </Card>

            <Card className="app-panel shadow-sm mb-3">
              <Card.Body className="p-3">
                <h5 className="panel-heading">Step output</h5>
                <div className="calib-log" ref={logRef}>
                  {currentLog.length === 0 ? (
                    <div className="console-empty">No output yet.</div>
                  ) : (
                    currentLog.map((line, i) => (
                      <div key={i} className="calib-log-line">
                        {line}
                      </div>
                    ))
                  )}
                </div>
              </Card.Body>
            </Card>
          </Col>
        </Row>
      </>
    );
  };

  // ------------------------------------------------------------------

  return (
    <div ref={wrapperRef}>
      <Row className="app-header g-3 align-items-center">
        <Col md="auto" className="brand-block">
          <div className="brand-mark">
            <span>Setup</span>
          </div>
          <h2 className="app-title">Camera calibration</h2>
        </Col>
        <Col>
          <div className="status-strip">
            <span className="status-pill">
              <span className="status-label">Session</span>
              <b>
                {status?.active
                  ? STEP_META[status.step as StepId]?.title ?? status.step
                  : status?.phase === "applying"
                  ? "Applying…"
                  : "Idle"}
              </b>
            </span>
            {status?.active && (
              <span className="status-pill">
                <span className="status-label">Cameras</span>
                {status.cameras_ok.filter(Boolean).length}/4 ok
              </span>
            )}
          </div>
        </Col>
        {status?.active && (
          <Col md="auto">
            <button
              type="button"
              className="btn btn-outline-danger"
              onClick={() =>
                setConfirm({
                  title: "Cancel calibration",
                  body: "Discard everything from this session? The current calibration stays untouched and tracking resumes.",
                  label: "Discard session",
                  variant: "danger",
                  action: () => act("calibration-cancel"),
                })
              }
            >
              Cancel session
            </button>
          </Col>
        )}
      </Row>

      {actionError && <div className="calib-error mb-3">{actionError}</div>}

      {!status && (
        <Card className="app-panel shadow-sm">
          <Card.Body className="p-4">
            <div className="empty-state">Waiting for backend&hellip;</div>
          </Card.Body>
        </Card>
      )}

      {status && status.phase === "applying" && (
        <Card className="app-panel shadow-sm mb-3">
          <Card.Body className="p-4">
            <div className="empty-state">Applying &amp; restarting tracker&hellip;</div>
          </Card.Body>
        </Card>
      )}

      {status && !status.active && status.phase !== "applying" && renderIdle()}
      {status && status.active && renderActive()}

      {confirm && (
        <div className="calib-modal-backdrop" onClick={() => setConfirm(null)}>
          <div className="calib-modal" onClick={(e) => e.stopPropagation()}>
            <h5 className="mb-2">{confirm.title}</h5>
            <p className="text-muted" style={{ fontSize: "0.9rem" }}>
              {confirm.body}
            </p>
            <div className="d-flex justify-content-end gap-2">
              <button
                type="button"
                className="btn btn-sm btn-outline-primary"
                onClick={() => setConfirm(null)}
              >
                Back
              </button>
              <button
                type="button"
                className={`btn btn-sm btn-${confirm.variant}`}
                onClick={() => {
                  const a = confirm.action;
                  setConfirm(null);
                  a();
                }}
              >
                {confirm.label}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
