import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    fs: {
      allow: [".."],
    },
    proxy: {
      "/assets": "http://127.0.0.1:8000",
      "/draft-worlds": "http://127.0.0.1:8000",
      "/worlds": "http://127.0.0.1:8000",
    },
  },
});
