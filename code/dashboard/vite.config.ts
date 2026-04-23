import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Proxy all /api and /ws requests to the FastAPI server during development
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/health": "http://localhost:8000",
      "/swarm": "http://localhost:8000",
      "/ws": {
        target: "ws://localhost:8000",
        ws: true,
      },
    },
  },
});
