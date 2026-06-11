"use client";

import { useEffect, useRef, useState } from "react";
import { Card, Col, Form, Row } from "react-bootstrap";

import { socket } from "../shared/styles/scripts/socket";

type LogEntry = {
  id: number;
  ts: number;
  kind: "in" | "out" | "err" | "sys";
  target: string;
  text: string;
};

type CommandRef = {
  name: string;
  format: string;
  description: string;
};

const COMMAND_REFERENCE: CommandRef[] = [
  {
    name: "arm",
    format: "arm <on|off>",
    description: "Arm or disarm the targeted drone(s).",
  },
  {
    name: "takeoff",
    format: "takeoff <z_meters>",
    description: "Climb to z and hold position.",
  },
  {
    name: "land",
    format: "land",
    description: "Descend and disarm at touchdown.",
  },
  {
    name: "goto",
    format: "goto <x> <y> <z>",
    description: "Move to absolute world position (meters).",
  },
  {
    name: "move",
    format: "move <dx> <dy> <dz>",
    description: "Move relative to current position.",
  },
  {
    name: "yaw",
    format: "yaw <radians>",
    description: "Rotate to absolute yaw angle.",
  },
  {
    name: "hover",
    format: "hover <seconds>",
    description: "Hold current setpoint for N seconds.",
  },
  {
    name: "trim",
    format: "trim <T> <R> <P> <Y>",
    description: "Apply stick trim values (us).",
  },
  {
    name: "pid",
    format: "pid <index> <value>",
    description: "Update a PID gain by index.",
  },
  {
    name: "estop",
    format: "estop",
    description: "Immediate motor cut on the targeted drone(s).",
  },
  {
    name: "ping",
    format: "ping",
    description: "Request a status echo from the targeted drone(s).",
  },
];

const FLEET_STORAGE_KEY = "drone-swarm-fleet-v1";

const loadFleet = (): { id: string; name: string; active: boolean }[] => {
  try {
    const raw = localStorage.getItem(FLEET_STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (Array.isArray(parsed)) {
      return parsed.map((d: any) => ({
        id: String(d.id),
        name: String(d.name ?? d.id),
        active: Boolean(d.active),
      }));
    }
  } catch {
    // ignore
  }
  return [];
};

const formatTime = (ts: number) => {
  const d = new Date(ts);
  return `${d.getHours().toString().padStart(2, "0")}:${d
    .getMinutes()
    .toString()
    .padStart(2, "0")}:${d.getSeconds().toString().padStart(2, "0")}`;
};

export default function ConsoleView() {
  const [target, setTarget] = useState<string>("all");
  const [input, setInput] = useState("");
  const [log, setLog] = useState<LogEntry[]>([]);
  const [fleet, setFleet] = useState(loadFleet);
  const logRef = useRef<HTMLDivElement | null>(null);
  const idRef = useRef(0);

  useEffect(() => {
    const id = setInterval(() => setFleet(loadFleet()), 2000);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    if (logRef.current) {
      logRef.current.scrollTop = logRef.current.scrollHeight;
    }
  }, [log]);

  useEffect(() => {
    const onAck = (data: { target?: string; text?: string }) => {
      pushLog("out", data.target ?? "swarm", data.text ?? "(no payload)");
    };
    const onErr = (data: { target?: string; text?: string }) => {
      pushLog("err", data.target ?? "swarm", data.text ?? "error");
    };
    socket.on("console-ack", onAck);
    socket.on("console-error", onErr);
    return () => {
      socket.off("console-ack", onAck);
      socket.off("console-error", onErr);
    };
  }, []);

  const pushLog = (kind: LogEntry["kind"], target: string, text: string) => {
    idRef.current += 1;
    setLog((prev) =>
      [
        ...prev,
        { id: idRef.current, ts: Date.now(), kind, target, text },
      ].slice(-500)
    );
  };

  const sendCommand = () => {
    const trimmed = input.trim();
    if (!trimmed) return;
    const parts = trimmed.split(/\s+/);
    const cmd = parts[0];
    const args = parts.slice(1);
    pushLog("in", target, trimmed);
    socket.emit("console-command", {
      target,
      command: cmd,
      args,
      raw: trimmed,
    });
    setInput("");
  };

  const clearLog = () => setLog([]);

  const onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") {
      e.preventDefault();
      sendCommand();
    }
  };

  return (
    <>
      <Row className="app-header g-3 align-items-center">
        <Col md="auto" className="brand-block">
          <div className="brand-mark">
            <span>Direct control</span>
          </div>
          <h2 className="app-title">Console</h2>
        </Col>
        <Col>
          <div className="status-strip">
            <span className="status-pill">
              <span className="status-label">Target</span>
              <b>{target}</b>
            </span>
            <span className="status-pill">
              <span className="status-label">Lines</span>
              <b>{log.length}</b>
            </span>
          </div>
        </Col>
      </Row>

      <Row className="g-4">
        <Col lg={8}>
          <Card className="app-panel shadow-sm mb-3">
            <Card.Body className="p-3 d-flex flex-column">
              <Row className="panel-heading align-items-center">
                <Col xs="auto">
                  <h5>Stream</h5>
                </Col>
                <Col className="panel-toolbar">
                  <button
                    type="button"
                    className="btn btn-sm btn-outline-danger"
                    onClick={clearLog}
                  >
                    Clear
                  </button>
                </Col>
              </Row>

              <div className="console-log" ref={logRef}>
                {log.length === 0 ? (
                  <div className="console-empty">
                    No history yet. Send a command below.
                  </div>
                ) : (
                  log.map((entry) => (
                    <div key={entry.id} className={`console-line console-${entry.kind}`}>
                      <span className="console-ts">{formatTime(entry.ts)}</span>
                      <span className="console-target">[{entry.target}]</span>
                      <span className="console-arrow">
                        {entry.kind === "in" ? "→" : entry.kind === "out" ? "←" : entry.kind === "err" ? "!" : "·"}
                      </span>
                      <span className="console-text">{entry.text}</span>
                    </div>
                  ))
                )}
              </div>

              <Row className="g-2 mt-3 align-items-center">
                <Col md={3}>
                  <Form.Select
                    size="sm"
                    value={target}
                    onChange={(e) => setTarget(e.target.value)}
                  >
                    <option value="all">All drones</option>
                    {fleet.map((d) => (
                      <option key={d.id} value={d.id}>
                        {d.name} {d.active ? "" : "(standby)"}
                      </option>
                    ))}
                  </Form.Select>
                </Col>
                <Col>
                  <Form.Control
                    type="text"
                    placeholder='e.g. "takeoff 0.5" or "goto 0 0 0.3"'
                    value={input}
                    onChange={(e) => setInput(e.target.value)}
                    onKeyDown={onKeyDown}
                  />
                </Col>
                <Col md="auto">
                  <button
                    type="button"
                    className="btn btn-primary"
                    onClick={sendCommand}
                    disabled={!input.trim()}
                  >
                    Send
                  </button>
                </Col>
              </Row>
            </Card.Body>
          </Card>
        </Col>

        <Col lg={4}>
          <Card className="app-panel shadow-sm mb-3">
            <Card.Body className="p-3">
              <h5 className="panel-heading">Commands</h5>
              <div className="command-list">
                {COMMAND_REFERENCE.map((cmd) => (
                  <button
                    key={cmd.name}
                    type="button"
                    className="command-card"
                    onClick={() => setInput(cmd.format.replace(/<[^>]+>/g, "").trim())}
                  >
                    <div className="command-name">{cmd.name}</div>
                    <code className="command-format">{cmd.format}</code>
                    <div className="command-desc">{cmd.description}</div>
                  </button>
                ))}
              </div>
            </Card.Body>
          </Card>
        </Col>
      </Row>
    </>
  );
}
