import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const proxyTarget = process.env.VITE_DEV_PROXY_TARGET || "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": proxyTarget,
      "/artifacts": proxyTarget,
      "/health": proxyTarget
    }
  }
});
