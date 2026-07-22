// PidErrorChart: rolling plot of the error between the controller setpoint
// and the tracked drone position, for PID tuning. Listens to the same
// "drone-state" socket event as MoCapView but uses the backend's `setpoint`
// field (the controller's live x_sp/y_sp/z_sp), so takeoff/landing ramps are
// reflected instead of the raw UI setpoint inputs.

import { useEffect, useRef, useState } from "react";
import { Col, Form, Row } from "react-bootstrap";
import {
  Chart as ChartJS,
  LinearScale,
  PointElement,
  LineElement,
  Legend,
  Tooltip,
  type ChartData,
  type ChartOptions,
} from "chart.js";
import { Line } from "react-chartjs-2";

import { socket } from "../shared/styles/scripts/socket";

ChartJS.register(LinearScale, PointElement, LineElement, Legend, Tooltip);

type Sample = {
  t: number;
  px: number; py: number; pz: number; // drone position
  sx: number; sy: number; sz: number; // controller setpoint
};

type ErrorMode = "xy" | "z";

// Span of the x axis: only the most recent WINDOW_S seconds are drawn.
// The full sample history is kept (until Clear) so CSV export covers the
// whole session, not just the visible window.
const WINDOW_S = 30;
// Chart redraw period. Samples still buffer at the backend's full emit rate
// (30 Hz); redrawing slower keeps React/chart.js work negligible.
const REDRAW_MS = 100;
// The error must stay inside the band this long before we call it settled;
// prevents declaring "settled" at a zero-crossing mid-oscillation.
const DWELL_S = 1.0;

const finite3 = (v: unknown): v is number[] =>
  Array.isArray(v) && v.length >= 3 && v.slice(0, 3).every(Number.isFinite);

const xyErr = (s: Sample) => Math.hypot(s.px - s.sx, s.py - s.sy);
const zErr = (s: Sample) => s.pz - s.sz;

// First index in `arr` (sorted by t) with t >= tMin. Binary search so the
// per-redraw window slice stays cheap even after hours of samples.
const lowerBound = (arr: Sample[], tMin: number) => {
  let lo = 0;
  let hi = arr.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (arr[mid].t < tMin) lo = mid + 1;
    else hi = mid;
  }
  return lo;
};

export default function PidErrorChart() {
  const [mode, setMode] = useState<ErrorMode>("xy");
  const [paused, setPaused] = useState(false);
  const [band, setBand] = useState("0.05");
  const [, setTick] = useState(0);

  const samplesRef = useRef<Sample[]>([]);
  const t0Ref = useRef<number | null>(null);
  const pausedRef = useRef(paused);
  pausedRef.current = paused;

  // Settling-time tracking: time of the last setpoint change, and the last
  // time each error was outside the band. Settled = inside band ever since,
  // for at least DWELL_S.
  const stepTRef = useRef<number | null>(null);
  const lastSpRef = useRef<number[] | null>(null);
  const lastOutXYRef = useRef(0);
  const lastOutZRef = useRef(0);
  const bandRef = useRef(0.05);

  useEffect(() => {
    const onState = (data: { pos?: number[] | null; setpoint?: number[] | null }) => {
      if (pausedRef.current) return;
      if (!finite3(data?.pos) || !finite3(data?.setpoint)) return;
      const now = performance.now() / 1000;
      if (t0Ref.current === null) t0Ref.current = now;
      const t = now - t0Ref.current;

      const s: Sample = {
        t,
        px: data.pos[0], py: data.pos[1], pz: data.pos[2],
        sx: data.setpoint[0], sy: data.setpoint[1], sz: data.setpoint[2],
      };

      const prevSp = lastSpRef.current;
      if (
        prevSp &&
        (Math.abs(s.sx - prevSp[0]) > 1e-9 ||
          Math.abs(s.sy - prevSp[1]) > 1e-9 ||
          Math.abs(s.sz - prevSp[2]) > 1e-9)
      ) {
        // Setpoint moved: restart the settling clock. During takeoff/landing
        // ramps this fires every sample, so settling ends up measured from
        // the end of the ramp — which is what we want.
        stepTRef.current = t;
        lastOutXYRef.current = t;
        lastOutZRef.current = t;
      }
      lastSpRef.current = [s.sx, s.sy, s.sz];

      if (xyErr(s) > bandRef.current) lastOutXYRef.current = t;
      if (Math.abs(zErr(s)) > bandRef.current) lastOutZRef.current = t;

      // Append-only: the whole session is kept so CSV export loses nothing.
      // Drawing slices out the visible window below.
      samplesRef.current.push(s);
    };
    socket.on("drone-state", onState);
    return () => {
      socket.off("drone-state", onState);
    };
  }, []);

  useEffect(() => {
    if (paused) return;
    const id = setInterval(() => setTick((x) => x + 1), REDRAW_MS);
    return () => clearInterval(id);
  }, [paused]);

  // When the band changes, rescan the buffer so the settle readout reflects
  // the new band immediately instead of only from now on.
  useEffect(() => {
    const b = parseFloat(band);
    if (!Number.isFinite(b) || b <= 0) return;
    bandRef.current = b;
    const st = stepTRef.current;
    if (st === null) return;
    let outXY = st;
    let outZ = st;
    for (const s of samplesRef.current) {
      if (s.t < st) continue;
      if (xyErr(s) > b) outXY = s.t;
      if (Math.abs(zErr(s)) > b) outZ = s.t;
    }
    lastOutXYRef.current = outXY;
    lastOutZRef.current = outZ;
  }, [band]);

  const clear = () => {
    samplesRef.current = [];
    t0Ref.current = null;
    stepTRef.current = null;
    lastSpRef.current = null;
    lastOutXYRef.current = 0;
    lastOutZRef.current = 0;
    setTick((x) => x + 1);
  };

  // Exports the FULL history since session start (or the last Clear), not
  // just the 30 s drawn on screen.
  const exportCsv = () => {
    const buf = samplesRef.current;
    if (buf.length === 0) return;
    const header = "t_s,pos_x,pos_y,pos_z,sp_x,sp_y,sp_z,err_x,err_y,err_z,err_xy";
    const lines = buf.map((s) =>
      [
        s.t,
        s.px, s.py, s.pz,
        s.sx, s.sy, s.sz,
        s.px - s.sx, s.py - s.sy, s.pz - s.sz,
        xyErr(s),
      ]
        .map((n) => n.toFixed(4))
        .join(","),
    );
    const blob = new Blob([[header, ...lines].join("\n")], { type: "text/csv" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `pid-error-${new Date().toISOString().replace(/[:.]/g, "-")}.csv`;
    a.click();
    URL.revokeObjectURL(a.href);
  };

  const history = samplesRef.current;
  const tLast = history.length > 0 ? history[history.length - 1].t : 0;
  // Only the last WINDOW_S seconds are drawn (and used for the RMS/Peak
  // readouts); the full history stays in the buffer for CSV export.
  const samples = history.slice(lowerBound(history, tLast - WINDOW_S));

  const data: ChartData<"line", { x: number; y: number }[]> = {
    datasets:
      mode === "xy"
        ? [
            {
              label: "|XY| error",
              data: samples.map((s) => ({ x: s.t, y: xyErr(s) })),
              borderColor: "rgb(33, 37, 41)",
              backgroundColor: "rgba(33, 37, 41, 0.5)",
              borderWidth: 2,
            },
            {
              label: "X error",
              data: samples.map((s) => ({ x: s.t, y: s.px - s.sx })),
              borderColor: "rgb(255, 0, 0)",
              backgroundColor: "rgba(255, 0, 0, 0.5)",
              borderWidth: 1,
            },
            {
              label: "Y error",
              data: samples.map((s) => ({ x: s.t, y: s.py - s.sy })),
              borderColor: "rgb(0, 160, 0)",
              backgroundColor: "rgba(0, 160, 0, 0.5)",
              borderWidth: 1,
            },
          ]
        : [
            {
              label: "Z error",
              data: samples.map((s) => ({ x: s.t, y: zErr(s) })),
              borderColor: "rgb(0, 0, 255)",
              backgroundColor: "rgba(0, 0, 255, 0.5)",
              borderWidth: 2,
            },
          ],
  };

  const options: ChartOptions<"line"> = {
    animation: false,
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: { position: "top", align: "start" },
      tooltip: { enabled: false },
    },
    scales: {
      x: {
        type: "linear",
        min: Math.max(0, tLast - WINDOW_S),
        max: Math.max(tLast, 5),
        title: { display: true, text: "time (s)" },
      },
      y: {
        title: { display: true, text: "error (m)" },
        grace: "10%",
      },
    },
    elements: { point: { radius: 0 } },
  };

  // RMS and worst-case error over the visible window for the selected mode —
  // the numbers to compare between PID trials.
  const errs =
    mode === "xy" ? samples.map(xyErr) : samples.map(zErr);
  const rms =
    errs.length > 0
      ? Math.sqrt(errs.reduce((acc, e) => acc + e * e, 0) / errs.length)
      : null;
  const peak =
    errs.length > 0 ? errs.reduce((acc, e) => Math.max(acc, Math.abs(e)), 0) : null;
  const current = errs.length > 0 ? errs[errs.length - 1] : null;

  // Settling time since the last setpoint change: "-" before any step, "…"
  // while still outside the band (or inside for less than DWELL_S).
  const stepT = stepTRef.current;
  const lastOut = mode === "xy" ? lastOutXYRef.current : lastOutZRef.current;
  let settle = "-";
  if (stepT !== null && samples.length > 0) {
    settle = tLast - lastOut >= DWELL_S ? `${(lastOut - stepT).toFixed(1)} s` : "…";
  }

  const fmt = (x: number | null) => (x === null ? "-" : x.toFixed(3));

  return (
    <>
      <Row className="panel-heading align-items-center g-2">
        <Col xs="auto">
          <h5>Setpoint error</h5>
        </Col>
        <Col xs="auto">
          <Form.Select
            size="sm"
            value={mode}
            onChange={(e) => setMode(e.target.value as ErrorMode)}
            style={{ width: 140 }}
          >
            <option value="xy">XY error</option>
            <option value="z">Z error</option>
          </Form.Select>
        </Col>
        <Col xs="auto" className="d-flex align-items-center">
          <small className="me-1 text-nowrap">band ±</small>
          <Form.Control
            size="sm"
            type="number"
            step="0.01"
            min="0.01"
            value={band}
            onChange={(e) => setBand(e.target.value)}
            style={{ width: 80 }}
          />
          <small className="ms-1">m</small>
        </Col>
        <Col>
          <div className="status-strip">
            <span className="status-pill">
              <span className="status-label">Current</span>
              {fmt(current)} m
            </span>
            <span className="status-pill">
              <span className="status-label">RMS ({WINDOW_S}s)</span>
              {fmt(rms)} m
            </span>
            <span className="status-pill">
              <span className="status-label">Peak ({WINDOW_S}s)</span>
              {fmt(peak)} m
            </span>
            <span className="status-pill">
              <span className="status-label">Settle</span>
              {settle}
            </span>
          </div>
        </Col>
        <Col xs="auto" className="panel-toolbar">
          <button
            type="button"
            className={`btn btn-sm ${paused ? "btn-outline-primary" : "btn-outline-secondary"}`}
            onClick={() => setPaused(!paused)}
          >
            {paused ? "Resume" : "Pause"}
          </button>{" "}
          <button
            type="button"
            className="btn btn-sm btn-outline-danger"
            onClick={clear}
          >
            Clear
          </button>{" "}
          <button
            type="button"
            className="btn btn-sm btn-outline-secondary"
            onClick={exportCsv}
            disabled={history.length === 0}
          >
            CSV
          </button>
        </Col>
      </Row>
      <div style={{ height: 260 }} className="mt-2">
        <Line options={options} data={data} />
      </div>
    </>
  );
}
