import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  build: {
    outDir: "dist",
  },
  server: {
    port: 5173,
    proxy: process.env.VITE_API_BASE
      ? undefined
      : {
          "/api": {
            target: process.env.VITE_DEV_PROXY_TARGET || "http://127.0.0.1:8686",
            changeOrigin: true,
          },
        },
  },
});
