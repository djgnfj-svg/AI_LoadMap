/** 라우팅은 해시 하나로 끝낸다 (R6 — 새 기술 추가 금지).
 *
 *   #/                                 내 로드맵 목록 (로그인 전이면 로그인 화면)
 *   #/new                              목표 입력 -> 생성
 *   #/{projectId}                      메인 (티켓 보드 + 다이어그램)
 *   #/{projectId}/review/{reviewDayId} 재점검 세션
 *
 * 로그인 여부는 /auth/me 한 번으로 정한다. 아니면 화면마다 401 을 따로 받아야 한다.
 */
import { useCallback, useEffect, useState } from "react";

import { authApi, type User } from "./api";
import { GoalInput } from "./screens/GoalInput";
import { Login } from "./screens/Login";
import { Main } from "./screens/Main";
import { ProjectList } from "./screens/ProjectList";
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
  const [user, setUser] = useState<User | null>(null);
  // 확인 전에는 로그인 화면도 목록도 그리지 않는다 — 새로고침마다 로그인 화면이
  // 한 번 번쩍이는 것을 막는다.
  const [checked, setChecked] = useState(false);

  useEffect(() => {
    authApi
      .me()
      .then((res) => setUser(res.user))
      .catch(() => setUser(null))
      .finally(() => setChecked(true));
  }, []);

  useEffect(() => {
    const onHashChange = () => setRoute(readRoute());
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  const go = useCallback((hash: string) => {
    window.location.hash = hash;
    setRoute(readRoute());
  }, []);

  const signOut = useCallback(() => {
    authApi.logout().finally(() => {
      setUser(null);
      go("");
    });
  }, [go]);

  if (!checked) return <div className="boot">불러오는 중…</div>;

  if (!user) {
    return (
      <Login
        onSignedIn={(signedIn) => {
          setUser(signedIn);
          go("");
        }}
      />
    );
  }

  if (route.projectId && route.reviewDayId) {
    return (
      <ReviewSession
        reviewDayId={route.reviewDayId}
        onBack={() => go(`/${route.projectId}`)}
        onApplied={() => undefined}
      />
    );
  }
  if (route.projectId === "new") {
    return <GoalInput onCreated={(id) => go(`/${id}`)} onBack={() => go("")} />;
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
  return (
    <ProjectList
      user={user}
      onOpen={(id) => go(`/${id}`)}
      onNew={() => go("/new")}
      onSignOut={signOut}
    />
  );
}
