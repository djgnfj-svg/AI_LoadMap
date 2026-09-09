/** 로그인하면 제일 먼저 보는 화면 — 내 로드맵 목록.
 *
 * 전에는 해시가 비면 곧장 목표 입력이었다. 로드맵이 여럿이 되면 그 화면은
 * 「돌아갈 곳」이 못 된다.
 */
import { useCallback, useEffect, useState } from "react";

import { api, type ProjectSummary, type User } from "../api";

interface Props {
  user: User;
  onOpen: (projectId: string) => void;
  onNew: () => void;
  onSignOut: () => void;
}

export function ProjectList({ user, onOpen, onNew, onSignOut }: Props) {
  const [projects, setProjects] = useState<ProjectSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    api
      .listProjects()
      .then((res) => setProjects(res.projects))
      .catch((e) => setError(String(e)));
  }, []);

  useEffect(load, [load]);

  return (
    <div className="list-screen">
      <header className="list-header">
        <h1>내 로드맵</h1>
        <div className="who">
          {user.avatar_url && <img src={user.avatar_url} alt="" width={28} height={28} />}
          <span>{user.display_name ?? user.email}</span>
          <button className="ghost" onClick={onSignOut}>
            로그아웃
          </button>
        </div>
      </header>

      {error && (
        <div className="notice error">
          <h4>목록을 불러오지 못했습니다</h4>
          <div className="sub">{error}</div>
        </div>
      )}

      {projects === null && !error && <p className="muted">불러오는 중…</p>}

      {projects?.length === 0 && (
        <div className="empty">
          <p>아직 만든 로드맵이 없습니다.</p>
          <button className="primary" onClick={onNew}>
            첫 로드맵 만들기
          </button>
        </div>
      )}

      {projects && projects.length > 0 && (
        <>
          <div className="actions">
            <button className="primary" onClick={onNew}>
              새 로드맵
            </button>
          </div>
          <ul className="project-cards">
            {projects.map((p) => {
              const done = p.resolved_count;
              const total = p.ticket_count;
              const percent = total > 0 ? Math.round((done / total) * 100) : 0;
              return (
                <li key={p.id}>
                  <button className="project-card" onClick={() => onOpen(p.id)}>
                    <div className="project-card-head">
                      <strong>{p.title}</strong>
                      <span className="muted">{p.start_date} 시작</span>
                    </div>
                    <p className="goal">{p.goal_text}</p>
                    <div className="bar" aria-hidden>
                      <i style={{ width: `${percent}%` }} />
                    </div>
                    <span className="muted">
                      {total > 0 ? `티켓 ${done} / ${total} · ${percent}%` : "아직 티켓이 없습니다"}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        </>
      )}
    </div>
  );
}
