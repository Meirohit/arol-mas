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
    },
  },
});
