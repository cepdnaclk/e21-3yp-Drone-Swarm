"use client";

import { useCallback, useEffect, useRef, useState } from "react";
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
  tag?: string;
};

// Tagged commands reach every active drone when the target is "All drones".
// The rest drive the single shared flight controller, so with "All drones"
// selected the backend sends them to the currently selected drone and says so.
const COMMAND_REFERENCE: CommandRef[] = [
  {
    name: "arm",
    format: "arm <on|off>",
    description:
      "Arm or disarm. With All drones selected this arms the whole fleet " +
      "(motors parked); only the tracked drone can fly. Disarm is always " +
      "fleet-wide.",
    tag: "whole fleet",
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
    tag: "whole fleet",
  },
  {
    name: "pid",
    format: "pid <index> <value>",
    description: "Update a PID gain by index.",
    tag: "whole fleet",
  },
  {
    name: "estop",
    format: "estop",
    description: "Immediate motor cut on the targeted drone(s).",
    tag: "whole fleet",
  },
  {
    name: "ping",
    format: "ping",
    description: "Status echo from the targeted drone(s).",
    tag: "whole fleet",
  },
];

const FLEET_STORAGE_KEY = "drone-swarm-fleet-v1";

const MAX_HISTORY = 100;

type FleetEntry = { id: string; name: string; active: boolean };

const parseFleet = (raw: unknown): FleetEntry[] =>
  Array.isArray(raw)
    ? raw
        .filter((d: any) => d && d.id != null)
        .map((d: any) => ({
          id: String(d.id),
          name: String(d.name ?? d.id),
          active: Boolean(d.active),
        }))
    : [];

// Seed from the cache DronesView writes so the picker is populated on first
// paint; the backend's "fleet" event is the source of truth from then on.
const loadCachedFleet = (): FleetEntry[] => {
  try {
    const raw = localStorage.getItem(FLEET_STORAGE_KEY);
    return raw ? parseFleet(JSON.parse(raw)) : [];
  } catch {
    return [];
  }
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
  const [fleet, setFleet] = useState<FleetEntry[]>(loadCachedFleet);
  const [connected, setConnected] = useState(socket.connected);
  const logRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const idRef = useRef(0);
  // Sent commands, newest last. posRef counts back from the newest while the
  // user is arrowing through; -1 means "editing a fresh line". A ref, not
  // state, so held-down arrow keys don't read a stale position mid-batch.
  const historyRef = useRef<string[]>([]);
  const posRef = useRef(-1);
  const draftRef = useRef("");
  // Only stick to the bottom while the user is already there, so scrolling up
  // to read older output isn't yanked away by the next incoming line.
  const pinnedRef = useRef(true);

  const pushLog = useCallback(
    (kind: LogEntry["kind"], entryTarget: string, text: string) => {
      idRef.current += 1;
      const id = idRef.current;
      const ts = Date.now();
      setLog((prev) =>
        [...prev, { id, ts, kind, target: entryTarget, text }].slice(-500)
      );
    },
    []
  );

  useEffect(() => {
    const onFleet = (data: { drones?: unknown }) => {
      setFleet(parseFleet(data?.drones));
    };
    socket.on("fleet", onFleet);
    return () => {
      socket.off("fleet", onFleet);
    };
  }, []);

  // Don't leave the picker pointing at a drone that was removed or put on
  // standby — commands to it would just bounce back as errors.
  useEffect(() => {
    if (target === "all") return;
    if (!fleet.some((d) => d.id === target && d.active)) setTarget("all");
  }, [fleet, target]);

  useEffect(() => {
    const el = logRef.current;
    if (el && pinnedRef.current) el.scrollTop = el.scrollHeight;
  }, [log]);

  useEffect(() => {
    const onAck = (data: { target?: string; text?: string }) => {
      pushLog("out", data?.target ?? "swarm", data?.text ?? "(no payload)");
    };
    const onErr = (data: { target?: string; text?: string }) => {
      pushLog("err", data?.target ?? "swarm", data?.text ?? "error");
    };
    const onNote = (data: { target?: string; text?: string }) => {
      pushLog("sys", data?.target ?? "swarm", data?.text ?? "");
    };
    const onConnect = () => {
      setConnected(true);
      pushLog("sys", "link", "connected to backend");
    };
    const onDisconnect = () => {
      setConnected(false);
      pushLog("err", "link", "disconnected from backend — commands will not be sent");
    };
    socket.on("console-ack", onAck);
    socket.on("console-error", onErr);
    socket.on("console-note", onNote);
    socket.on("connect", onConnect);
    socket.on("disconnect", onDisconnect);
    return () => {
      socket.off("console-ack", onAck);
      socket.off("console-error", onErr);
      socket.off("console-note", onNote);
      socket.off("connect", onConnect);
      socket.off("disconnect", onDisconnect);
    };
  }, [pushLog]);

  const targetLabel =
    target === "all"
      ? "all drones"
      : fleet.find((d) => d.id === target)?.name ?? target;

  const sendCommand = () => {
    const trimmed = input.trim();
    if (!trimmed) return;
    const parts = trimmed.split(/\s+/);
    const cmd = parts[0];
    const args = parts.slice(1);
    pushLog("in", targetLabel, trimmed);
    if (!socket.connected) {
      pushLog("err", "link", "not connected to the backend — command dropped");
      return;
    }
    socket.emit("console-command", {
      target,
      command: cmd,
      args,
      raw: trimmed,
    });
    const history = historyRef.current;
    if (history[history.length - 1] !== trimmed) {
      history.push(trimmed);
      if (history.length > MAX_HISTORY) history.shift();
    }
    posRef.current = -1;
    draftRef.current = "";
    setInput("");
  };

  const clearLog = () => setLog([]);

  const recall = (delta: number) => {
    const history = historyRef.current;
    if (history.length === 0) return;
    const next = posRef.current + delta;
    if (next < 0) {
      // Back past the newest entry: restore whatever was being typed.
      if (posRef.current === -1) return;
      posRef.current = -1;
      setInput(draftRef.current);
      return;
    }
    if (next >= history.length) return;
    if (posRef.current === -1) draftRef.current = input;
    posRef.current = next;
    setInput(history[history.length - 1 - next]);
  };

  const insertCommand = (name: string) => {
    setInput(`${name} `);
    posRef.current = -1;
    inputRef.current?.focus();
  };

  const onLogScroll = () => {
    const el = logRef.current;
    if (!el) return;
    pinnedRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 24;
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") {
      e.preventDefault();
      sendCommand();
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      recall(1);
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      recall(-1);
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
              <b>{targetLabel}</b>
            </span>
            <span className="status-pill">
              <span className="status-label">Lines</span>
              <b>{log.length}</b>
            </span>
            <span className="status-pill">
              <span className="status-label">Link</span>
              <b>{connected ? "online" : "offline"}</b>
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

              <div className="console-log" ref={logRef} onScroll={onLogScroll}>
                {log.length === 0 ? (
                  <div className="console-empty">
                    No history yet. Send a command below. Use ↑/↓ to recall
                    previous commands.
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
                      <option key={d.id} value={d.id} disabled={!d.active}>
                        {d.active ? d.name : `${d.name} (standby)`}
                      </option>
                    ))}
                  </Form.Select>
                </Col>
                <Col>
                  <Form.Control
                    ref={inputRef}
                    type="text"
                    placeholder='e.g. "takeoff 0.5" or "goto 0 0 0.3"'
                    value={input}
                    onChange={(e) => {
                      setInput(e.target.value);
                      posRef.current = -1;
                    }}
                    onKeyDown={onKeyDown}
                  />
                </Col>
                <Col md="auto">
                  <button
                    type="button"
                    className="btn btn-primary"
                    onClick={sendCommand}
                    disabled={!input.trim() || !connected}
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
                    onClick={() => insertCommand(cmd.name)}
                  >
                    <div className="command-name">
                      {cmd.name}
                      {cmd.tag && <span className="command-tag">{cmd.tag}</span>}
                    </div>
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
