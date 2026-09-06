import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// 개발 중에는 FastAPI 로 프록시한다. CORS 설정이 필요 없어진다.
const backend = process.env.BACKEND_URL ?? "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/projects": backend,
      "/tickets": backend,
      "/reviews": backend,
      "/health": backend,
    },
  },
});
