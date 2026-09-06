/** 라우팅은 해시 하나로 끝낸다 (R6 — 새 기술 추가 금지). */
import { useEffect, useState } from "react";

import { GoalInput } from "./screens/GoalInput";
import { Main } from "./screens/Main";

function readProjectId(): string | null {
  const id = window.location.hash.replace(/^#\/?/, "").trim();
  return id.length > 0 ? id : null;
}

export default function App() {
  const [projectId, setProjectId] = useState<string | null>(readProjectId);

  useEffect(() => {
    const onHashChange = () => setProjectId(readProjectId());
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  const open = (id: string) => {
    window.location.hash = `/${id}`;
    setProjectId(id);
  };

  const back = () => {
    window.location.hash = "";
    setProjectId(null);
  };

  return projectId ? (
    <Main projectId={projectId} onBack={back} />
  ) : (
    <GoalInput onCreated={open} />
  );
}
