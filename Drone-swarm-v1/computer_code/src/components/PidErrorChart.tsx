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

type Sample = { t: number; ex: number; ey: number; ez: number };

type ErrorMode = "xy" | "z";

// Rolling window kept in the buffer and shown on the x axis.
const WINDOW_S = 30;
// Chart redraw period. Samples still buffer at the backend's full emit rate
// (30 Hz); redrawing slower keeps React/chart.js work negligible.
const REDRAW_MS = 100;

const finite3 = (v: unknown): v is number[] =>
  Array.isArray(v) && v.length >= 3 && v.slice(0, 3).every(Number.isFinite);

export default function PidErrorChart() {
  const [mode, setMode] = useState<ErrorMode>("xy");
  const [paused, setPaused] = useState(false);
  const [, setTick] = useState(0);

  const samplesRef = useRef<Sample[]>([]);
  const t0Ref = useRef<number | null>(null);
  const pausedRef = useRef(paused);
  pausedRef.current = paused;

  useEffect(() => {
    const onState = (data: { pos?: number[] | null; setpoint?: number[] | null }) => {
      if (pausedRef.current) return;
      if (!finite3(data?.pos) || !finite3(data?.setpoint)) return;
      const now = performance.now() / 1000;
      if (t0Ref.current === null) t0Ref.current = now;
      const t = now - t0Ref.current;
      const buf = samplesRef.current;
      buf.push({
        t,
        ex: data.pos[0] - data.setpoint[0],
        ey: data.pos[1] - data.setpoint[1],
        ez: data.pos[2] - data.setpoint[2],
      });
      while (buf.length > 0 && buf[0].t < t - WINDOW_S) buf.shift();
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

  const clear = () => {
    samplesRef.current = [];
    t0Ref.current = null;
    setTick((x) => x + 1);
  };

  const samples = samplesRef.current;
  const tLast = samples.length > 0 ? samples[samples.length - 1].t : 0;

  const data: ChartData<"line", { x: number; y: number }[]> = {
    datasets:
      mode === "xy"
        ? [
            {
              label: "|XY| error",
              data: samples.map((s) => ({ x: s.t, y: Math.hypot(s.ex, s.ey) })),
              borderColor: "rgb(33, 37, 41)",
              backgroundColor: "rgba(33, 37, 41, 0.5)",
              borderWidth: 2,
            },
            {
              label: "X error",
              data: samples.map((s) => ({ x: s.t, y: s.ex })),
              borderColor: "rgb(255, 0, 0)",
              backgroundColor: "rgba(255, 0, 0, 0.5)",
              borderWidth: 1,
            },
            {
              label: "Y error",
              data: samples.map((s) => ({ x: s.t, y: s.ey })),
              borderColor: "rgb(0, 160, 0)",
              backgroundColor: "rgba(0, 160, 0, 0.5)",
              borderWidth: 1,
            },
          ]
        : [
            {
              label: "Z error",
              data: samples.map((s) => ({ x: s.t, y: s.ez })),
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
    mode === "xy"
      ? samples.map((s) => Math.hypot(s.ex, s.ey))
      : samples.map((s) => s.ez);
  const rms =
    errs.length > 0
      ? Math.sqrt(errs.reduce((acc, e) => acc + e * e, 0) / errs.length)
      : null;
  const peak =
    errs.length > 0 ? errs.reduce((acc, e) => Math.max(acc, Math.abs(e)), 0) : null;
  const current = errs.length > 0 ? errs[errs.length - 1] : null;

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
          </button>
        </Col>
      </Row>
      <div style={{ height: 260 }} className="mt-2">
        <Line options={options} data={data} />
      </div>
    </>
  );
}
