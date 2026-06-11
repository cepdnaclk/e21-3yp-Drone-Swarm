"use client";

import { useState } from "react";
import { Container } from "react-bootstrap";

import Sidebar, { SectionId } from "./components/Sidebar";
import MoCapView from "./sections/MoCapView";
import DronesView from "./sections/DronesView";
import ConsoleView from "./sections/ConsoleView";
import UploadView from "./sections/UploadView";
import CalibrationView from "./sections/CalibrationView";

export default function App() {
  const [section, setSection] = useState<SectionId>("mocap");

  return (
    <div className="app-layout">
      <Sidebar active={section} onSelect={setSection} />
      <main className="app-main">
        <Container fluid className="app-shell">
          {section === "mocap" && <MoCapView />}
          {section === "drones" && <DronesView />}
          {section === "console" && <ConsoleView />}
          {section === "upload" && <UploadView />}
          {section === "calibration" && <CalibrationView />}
        </Container>
      </main>
    </div>
  );
}
