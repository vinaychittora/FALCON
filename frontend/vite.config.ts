import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    // Windows edits through WSL can emit a change before the file write completes.
    watch: { awaitWriteFinish: { stabilityThreshold: 250, pollInterval: 50 } },
    proxy: { "/api": { target: "http://127.0.0.1:8000", ws: true } },
  },
});
