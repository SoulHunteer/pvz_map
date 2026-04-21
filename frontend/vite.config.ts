import { resolve } from "path";

import react from "@vitejs/plugin-react";
import { defineConfig, type PluginOption } from "vite";

const proxyTarget = process.env.VITE_DEV_PROXY_TARGET || "http://localhost:8000";

// В dev-сервере делаем то же, что nginx в проде: URL /app/* отдаёт app.html,
// чтобы React Router (basename="/app") корректно резолвил маршруты.
function appRewrite(): PluginOption {
  return {
    name: "app-dev-rewrite",
    configureServer(server) {
      server.middlewares.use((req, _res, next) => {
        const url = req.url || "";
        // Точное /app или /app/... — всё, что не ассет
        if (url === "/app" || url.startsWith("/app/") || url.startsWith("/app?")) {
          req.url = "/app.html";
        }
        next();
      });
    },
  };
}

export default defineConfig({
  plugins: [react(), appRewrite()],
  build: {
    rollupOptions: {
      input: {
        // Статический лендинг (React через CDN, без Vite-обработки по сути)
        main: resolve(__dirname, "index.html"),
        // SPA-кабинет
        app: resolve(__dirname, "app.html"),
      },
    },
  },
  server: {
    proxy: {
      "/api": proxyTarget,
      "/artifacts": proxyTarget,
      "/health": proxyTarget,
    },
  },
});
