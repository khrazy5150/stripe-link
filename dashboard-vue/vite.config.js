import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    strictPort: false,
    // Allow importing the shared composition_rules.json from ../src (Page Composer single source of truth).
    fs: { allow: [".."] },
    proxy: {
      "/api": {
        target: "https://dev.juniorbay.com",
        changeOrigin: true,
        secure: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
      "/api-live": {
        target: "https://prod.juniorbay.com",
        changeOrigin: true,
        secure: true,
        rewrite: (path) => path.replace(/^\/api-live/, ""),
      },
    },
  },
});
