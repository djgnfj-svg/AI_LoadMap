import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// 개발 중에는 FastAPI 로 프록시한다. CORS 설정이 필요 없어진다.
const backend = process.env.BACKEND_URL ?? "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/auth": backend,
      "/projects": backend,
      "/tickets": backend,
      "/reviews": backend,
      // 알람 확인(/alerts/{id}/ack)은 /projects 밑에 있지 않다. 빠뜨리면 개발 중에만
      // 404 가 나고 (vite 가 index.html 을 돌려준다) 배포하면 멀쩡해 보인다.
      "/alerts": backend,
      "/health": backend,
    },
  },
});
