import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  // Same-origin /api in dev, exactly as Caddy will serve it in production (M4). No CORS needed.
  // 127.0.0.1, not localhost: Node may resolve localhost to ::1, where uvicorn is not listening.
  server: { proxy: { "/api": "http://127.0.0.1:8000" } },
});
