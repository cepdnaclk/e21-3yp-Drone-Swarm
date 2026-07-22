// Base URL of the Python backend (Flask + Socket.IO).
//
// In production the packaged app has Flask serve BOTH this built frontend and
// the Socket.IO / HTTP API from the same origin, so the correct value is an
// empty string ("" => same origin). During development the Vite dev server
// (:5173) proxies "/socket.io" and "/api" to the backend on :3001 (see
// vite.config.ts), so same-origin also works there without any override.
//
// Set VITE_BACKEND_URL only if you need to point the UI at a backend on a
// different origin (e.g. another machine).
export const BACKEND_URL: string = import.meta.env.VITE_BACKEND_URL ?? "";

// Absolute URL for the MJPEG camera stream endpoint. Relative in same-origin
// mode so it resolves against whatever host is serving the page.
export const CAMERA_STREAM_URL = `${BACKEND_URL}/api/camera-stream`;
