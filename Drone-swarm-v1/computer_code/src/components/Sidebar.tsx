"use client";

export type SectionId =
  | "mocap"
  | "drones"
  | "console"
  | "upload"
  | "calibration";

type NavItem = {
  id: SectionId;
  label: string;
  hint: string;
  icon: string;
};

const NAV_ITEMS: NavItem[] = [
  { id: "mocap", label: "MoCap", hint: "Single drone capture", icon: "M" },
  { id: "drones", label: "Drones", hint: "Fleet & status", icon: "D" },
  { id: "console", label: "Console", hint: "Command stream", icon: "C" },
  { id: "upload", label: "Algorithm", hint: "Upload .py script", icon: "U" },
  { id: "calibration", label: "Calibration", hint: "Camera intrinsics", icon: "K" },
];

type Props = {
  active: SectionId;
  onSelect: (id: SectionId) => void;
};

export default function Sidebar({ active, onSelect }: Props) {
  return (
    <aside className="app-sidebar">
      <div className="sidebar-brand">
        <div className="sidebar-logo" />
        <div className="sidebar-brand-text">
          <span className="sidebar-eyebrow">Drone</span>
          <span className="sidebar-title">Configurator</span>
        </div>
      </div>

      <nav className="sidebar-nav">
        {NAV_ITEMS.map((item) => {
          const isActive = item.id === active;
          return (
            <button
              key={item.id}
              type="button"
              className={`sidebar-link${isActive ? " is-active" : ""}`}
              onClick={() => onSelect(item.id)}
            >
              <span className="sidebar-link-icon">{item.icon}</span>
              <span className="sidebar-link-body">
                <span className="sidebar-link-label">{item.label}</span>
                <span className="sidebar-link-hint">{item.hint}</span>
              </span>
            </button>
          );
        })}
      </nav>

      <div className="sidebar-footer">
        <span className="sidebar-eyebrow">Build</span>
        <span className="sidebar-footer-version">v1 · single drone</span>
      </div>
    </aside>
  );
}
