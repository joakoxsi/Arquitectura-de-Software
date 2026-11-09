import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// En desarrollo, /graphql (y la API REST /api) se redirigen al API Gateway (puerto 8080).
const gateway = process.env.GATEWAY_URL ?? "http://localhost:8080";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: { "/graphql": gateway, "/api": gateway },
  },
});
