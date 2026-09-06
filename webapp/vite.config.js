import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Simple dev proxy so the frontend can call /api/* without CORS setup.
// In production, point VITE_API_BASE at the deployed backend URL instead.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
      // Report Markdown embeds images as relative "plots/..." paths,
      // which server.py rewrites to "/report-files/plots/...". Without
      // this proxy entry those requests hit the Vite dev server (5173)
      // instead of FastAPI (8000) and 404.
      "/report-files": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
});
