"use client";

import { useEffect, useRef, useState } from "react";
import { Card, Col, Row } from "react-bootstrap";

import { socket } from "../shared/styles/scripts/socket";

type PremadeFn = {
  name: string;
  signature: string;
  description: string;
};

const PREMADE_FUNCTIONS: PremadeFn[] = [
  {
    name: "arm",
    signature: "arm() -> None",
    description: "Arm the drone. Blocks until the controller reaches READY.",
  },
  {
    name: "disarm",
    signature: "disarm() -> None",
    description: "Disarm immediately.",
  },
  {
    name: "takeoff",
    signature: "takeoff(z: float) -> None",
    description: "Climb to z meters. Blocks until HOVER is reached.",
  },
  {
    name: "land",
    signature: "land() -> None",
    description: "Descend and disarm at touchdown. Blocks until landed.",
  },
  {
    name: "goto",
    signature: "goto(x: float, y: float, z: float) -> None",
    description: "Retarget the setpoint to an absolute world position (non-blocking).",
  },
  {
    name: "move",
    signature: "move(dx: float, dy: float, dz: float) -> None",
    description: "Shift the setpoint relative to the current one (non-blocking).",
  },
  {
    name: "set_yaw",
    signature: "set_yaw(yaw: float) -> None",
    description: "Rotate to an absolute yaw (radians).",
  },
  {
    name: "wait",
    signature: "wait(seconds: float) -> None",
    description: "Sleep. Use after goto/move to let the drone get there.",
  },
  {
    name: "get_position",
    signature: "get_position() -> tuple[float, float, float] | None",
    description: "Latest tracked world position in metres.",
  },
  {
    name: "get_battery",
    signature: "get_battery(drone_id: str) -> float | None",
    description: "Battery percentage by drone id, name, or MAC.",
  },
  {
    name: "get_state",
    signature: "get_state() -> str",
    description: "Controller state (IDLE, READY, TAKEOFF, HOVER, ...).",
  },
  {
    name: "list_active",
    signature: "list_active() -> list[str]",
    description: "Ids of all drones currently marked active.",
  },
  {
    name: "on_telemetry",
    signature: "on_telemetry(callback) -> None",
    description: "Register a callback fired on every battery telemetry packet.",
  },
  {
    name: "log / print",
    signature: "log(*args) -> None",
    description: "Write a line to the run log below.",
  },
];

type UploadStatus = "idle" | "uploading" | "success" | "error";
type RunStatus = "idle" | "running" | "finished" | "error" | "stopped";

type RunLogEntry = {
  id: number;
  stream: "out" | "err" | "sys";
  text: string;
};

const formatSize = (bytes: number) => {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
};

export default function UploadView() {
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<string>("");
  const [status, setStatus] = useState<UploadStatus>("idle");
  const [message, setMessage] = useState<string>("");
  const [dragOver, setDragOver] = useState(false);
  const inputRef = useRef<HTMLInputElement | null>(null);

  const [runStatus, setRunStatus] = useState<RunStatus>("idle");
  const [runLog, setRunLog] = useState<RunLogEntry[]>([]);
  const runLogRef = useRef<HTMLDivElement | null>(null);
  const logIdRef = useRef(0);

  useEffect(() => {
    const onLog = (data: { text?: string; stream?: string }) => {
      logIdRef.current += 1;
      const stream =
        data.stream === "err" || data.stream === "sys" ? data.stream : "out";
      setRunLog((prev) =>
        [
          ...prev,
          { id: logIdRef.current, stream, text: data.text ?? "" } as RunLogEntry,
        ].slice(-500)
      );
    };
    const onStatus = (data: { status?: string; error?: string }) => {
      const s = data.status;
      if (s === "running" || s === "finished" || s === "error" || s === "stopped") {
        setRunStatus(s);
      }
    };
    socket.on("algorithm-log", onLog);
    socket.on("algorithm-status", onStatus);
    return () => {
      socket.off("algorithm-log", onLog);
      socket.off("algorithm-status", onStatus);
    };
  }, []);

  useEffect(() => {
    if (runLogRef.current) {
      runLogRef.current.scrollTop = runLogRef.current.scrollHeight;
    }
  }, [runLog]);

  const pickFile = (f: File | null) => {
    setStatus("idle");
    setMessage("");
    if (!f) {
      setFile(null);
      setPreview("");
      return;
    }
    if (!f.name.toLowerCase().endsWith(".py")) {
      setFile(null);
      setPreview("");
      setStatus("error");
      setMessage("Only .py files are supported.");
      return;
    }
    setFile(f);
    const reader = new FileReader();
    reader.onload = () => {
      const text = typeof reader.result === "string" ? reader.result : "";
      setPreview(text.split("\n").slice(0, 40).join("\n"));
    };
    reader.readAsText(f);
  };

  const onInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    pickFile(e.target.files?.[0] ?? null);
  };

  const onDrop = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setDragOver(false);
    pickFile(e.dataTransfer.files?.[0] ?? null);
  };

  const uploadFile = async () => {
    if (!file) return;
    setStatus("uploading");
    setMessage("");
    setRunLog([]);
    try {
      const text = await file.text();
      socket.emit(
        "algorithm-upload",
        { filename: file.name, size: file.size, source: text },
        (ack: { ok?: boolean; error?: string } | undefined) => {
          if (ack && ack.ok) {
            setStatus("success");
            setMessage(`${file.name} accepted — running.`);
          } else if (ack && ack.error) {
            setStatus("error");
            setMessage(ack.error);
          } else {
            setStatus("success");
            setMessage(`${file.name} sent.`);
          }
        }
      );
    } catch (err) {
      setStatus("error");
      setMessage(err instanceof Error ? err.message : "Upload failed.");
    }
  };

  const stopAlgorithm = () => {
    socket.emit("algorithm-stop", {});
  };

  const clear = () => {
    setFile(null);
    setPreview("");
    setStatus("idle");
    setMessage("");
    if (inputRef.current) inputRef.current.value = "";
  };

  return (
    <>
      <Row className="app-header g-3 align-items-center">
        <Col md="auto" className="brand-block">
          <div className="brand-mark">
            <span>Mission script</span>
          </div>
          <h2 className="app-title">Upload algorithm</h2>
        </Col>
        <Col>
          <div className="status-strip">
            <span className="status-pill">
              <span className="status-label">File</span>
              <b>{file ? file.name : "—"}</b>
            </span>
            <span className="status-pill">
              <span className="status-label">Upload</span>
              <b>{status}</b>
            </span>
            <span className="status-pill">
              <span className="status-label">Run</span>
              <b>{runStatus}</b>
            </span>
          </div>
        </Col>
      </Row>

      <Row className="g-4">
        <Col lg={7}>
          <Card className="app-panel shadow-sm mb-3">
            <Card.Body className="p-3">
              <h5 className="panel-heading">Script</h5>

              <div
                className={`upload-dropzone${dragOver ? " is-over" : ""}${
                  file ? " has-file" : ""
                }`}
                onDragOver={(e) => {
                  e.preventDefault();
                  setDragOver(true);
                }}
                onDragLeave={() => setDragOver(false)}
                onDrop={onDrop}
                onClick={() => inputRef.current?.click()}
                role="button"
                tabIndex={0}
              >
                <input
                  ref={inputRef}
                  type="file"
                  accept=".py"
                  className="upload-input"
                  onChange={onInputChange}
                />
                {file ? (
                  <div className="upload-file">
                    <div className="upload-file-name">{file.name}</div>
                    <div className="upload-file-meta">{formatSize(file.size)}</div>
                  </div>
                ) : (
                  <div className="upload-prompt">
                    <div className="upload-icon">.py</div>
                    <div className="upload-prompt-title">
                      Drop a Python file or click to browse
                    </div>
                    <div className="upload-prompt-sub">
                      The script can call any premade function listed on the right.
                    </div>
                  </div>
                )}
              </div>

              <div className="upload-actions">
                <button
                  type="button"
                  className="btn btn-primary"
                  onClick={uploadFile}
                  disabled={!file || status === "uploading" || runStatus === "running"}
                >
                  {status === "uploading"
                    ? "Uploading…"
                    : runStatus === "running"
                      ? "Running…"
                      : "Upload & run"}
                </button>
                <button
                  type="button"
                  className="btn btn-danger"
                  onClick={stopAlgorithm}
                  disabled={runStatus !== "running"}
                >
                  Stop
                </button>
                <button
                  type="button"
                  className="btn btn-outline-danger"
                  onClick={clear}
                  disabled={!file || runStatus === "running"}
                >
                  Clear
                </button>
                {message && (
                  <span
                    className={`upload-message upload-${status}`}
                  >
                    {message}
                  </span>
                )}
              </div>

              {(runLog.length > 0 || runStatus !== "idle") && (
                <>
                  <h6 className="section-subhead mt-4">Run log</h6>
                  <div className="console-log upload-run-log" ref={runLogRef}>
                    {runLog.length === 0 ? (
                      <div className="console-empty">Waiting for output…</div>
                    ) : (
                      runLog.map((entry) => (
                        <div
                          key={entry.id}
                          className={`console-line console-${entry.stream}`}
                        >
                          <span className="console-text">{entry.text}</span>
                        </div>
                      ))
                    )}
                  </div>
                </>
              )}

              {preview && (
                <>
                  <h6 className="section-subhead mt-4">Preview</h6>
                  <pre className="upload-preview">{preview}</pre>
                </>
              )}
            </Card.Body>
          </Card>
        </Col>

        <Col lg={5}>
          <Card className="app-panel shadow-sm mb-3">
            <Card.Body className="p-3">
              <h5 className="panel-heading">Available functions</h5>
              <div className="fn-list">
                {PREMADE_FUNCTIONS.map((fn) => (
                  <div key={fn.name} className="fn-card">
                    <code className="fn-signature">{fn.signature}</code>
                    <div className="fn-desc">{fn.description}</div>
                  </div>
                ))}
              </div>
            </Card.Body>
          </Card>
        </Col>
      </Row>
    </>
  );
}
