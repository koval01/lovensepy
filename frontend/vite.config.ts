import { fileURLToPath, URL } from "node:url";

import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

/**
 * Paths owned by the FastAPI service. During `npm run dev` they are proxied to a
 * running service so the UI behaves exactly like the bundled build (same origin,
 * no CORS), including the `/ws` upgrade.
 */
const API_PATHS = [
  "/health",
  "/meta",
  "/state",
  "/config",
  "/toys",
  "/tasks",
  "/command",
  "/ble",
  "/socket",
  "/system",
  "/openapi.json",
  "/docs",
  "/redoc",
];

const target = process.env.LOVENSE_SERVICE_URL ?? "http://127.0.0.1:8000";

export default defineConfig({
  // Relative asset URLs keep the build working behind a reverse-proxy sub-path.
  base: "./",
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  build: {
    // Shipped inside the wheel and read by lovensepy/services/http_api/webui.py.
    outDir: "../lovensepy/services/http_api/webui_dist",
    emptyOutDir: true,
    sourcemap: false,
    chunkSizeWarningLimit: 900,
  },
  server: {
    port: 5173,
    strictPort: false,
    proxy: {
      ...Object.fromEntries(API_PATHS.map((path) => [path, { target, changeOrigin: true }])),
      "/ws": { target, ws: true },
    },
  },
});
