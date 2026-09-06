/** 라우팅은 해시 하나로 끝낸다 (R6 — 새 기술 추가 금지).
 *
 *   #/{projectId}                      메인 (티켓 보드 + 다이어그램)
 *   #/{projectId}/review/{reviewDayId} 재점검 세션
 */
import { useCallback, useEffect, useState } from "react";

import { GoalInput } from "./screens/GoalInput";
import { Main } from "./screens/Main";
import { ReviewSession } from "./screens/ReviewSession";

interface Route {
  projectId: string | null;
  reviewDayId: string | null;
}

function readRoute(): Route {
  const parts = window.location.hash.replace(/^#\/?/, "").split("/").filter(Boolean);
  return {
    projectId: parts[0] ?? null,
    reviewDayId: parts[1] === "review" ? (parts[2] ?? null) : null,
  };
}

export default function App() {
  const [route, setRoute] = useState<Route>(readRoute);

  useEffect(() => {
    const onHashChange = () => setRoute(readRoute());
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  const go = useCallback((hash: string) => {
    window.location.hash = hash;
    setRoute(readRoute());
  }, []);

  if (route.projectId && route.reviewDayId) {
    return (
      <ReviewSession
        reviewDayId={route.reviewDayId}
        onBack={() => go(`/${route.projectId}`)}
        onApplied={() => undefined}
      />
    );
  }
  if (route.projectId) {
    return (
      <Main
        projectId={route.projectId}
        onBack={() => go("")}
        onOpenReview={(id) => go(`/${route.projectId}/review/${id}`)}
      />
    );
  }
  return <GoalInput onCreated={(id) => go(`/${id}`)} />;
}
