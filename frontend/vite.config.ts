import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": {
        target: process.env.MIANSHI_API_URL || "http://127.0.0.1:8000",
      },
      "/health": {
        target: process.env.MIANSHI_API_URL || "http://127.0.0.1:8000",
      },
    },
  },
  preview: {
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": {
        target: process.env.MIANSHI_API_URL || "http://127.0.0.1:8000",
      },
      "/health": {
        target: process.env.MIANSHI_API_URL || "http://127.0.0.1:8000",
      },
    },
  },
});
