"use client";

import { useState } from "react";
import { Container } from "react-bootstrap";

import Sidebar, { SectionId } from "./components/Sidebar";
import MoCapView from "./sections/MoCapView";
import DronesView from "./sections/DronesView";
import ConsoleView from "./sections/ConsoleView";
import UploadView from "./sections/UploadView";
import CalibrationView from "./sections/CalibrationView";
import CameraSettingsView from "./sections/CameraSettingsView";

// Every section stays mounted; switching pages only toggles visibility.
// This preserves each view's state (PID edits, console history, running
// algorithm logs, calibration progress) and keeps their socket streams alive.
const SECTIONS: { id: SectionId; view: JSX.Element }[] = [
  { id: "mocap", view: <MoCapView /> },
  { id: "drones", view: <DronesView /> },
  { id: "console", view: <ConsoleView /> },
  { id: "upload", view: <UploadView /> },
  { id: "calibration", view: <CalibrationView /> },
  { id: "camera-settings", view: <CameraSettingsView /> },
];

export default function App() {
  const [section, setSection] = useState<SectionId>("mocap");

  return (
    <div className="app-layout">
      <Sidebar active={section} onSelect={setSection} />
      <main className="app-main">
        <Container fluid className="app-shell">
          {SECTIONS.map(({ id, view }) => (
            <div key={id} style={{ display: id === section ? undefined : "none" }}>
              {view}
            </div>
          ))}
        </Container>
      </main>
    </div>
  );
}
