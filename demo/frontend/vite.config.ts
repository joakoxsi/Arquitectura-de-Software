import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// En desarrollo, /api se redirige al API Gateway (puerto 8080 del host).
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: { "/api": process.env.GATEWAY_URL ?? "http://localhost:8080" },
  },
});
