/** 완성 청사진 (SPEC §3.3).
 *
 * 인터뷰에서 「무엇이 되면 끝났다고 할 수 있나요」에 답한 것이 여기 그대로 있다.
 * 기준마다 **어느 주가 맡는지**와 그 주가 얼마나 갔는지를 같이 보여준다 —
 * 계획이 그 기준을 향해 가고 있는지는 진행률이 아니라 이 대응이 말해준다.
 *
 * 어느 주도 안 맡은 기준은 생성 단계에서 critic 이 막는다. 그래도 남는 경우
 * (재시도 소진 후 결정적 복구)를 위해 「맡은 주 없음」을 숨기지 않고 드러낸다.
 */
import type { ProjectView } from "../api";

export function BlueprintPanel({ view }: { view: ProjectView }) {
  const criteria = view.project.blueprint?.criteria ?? [];
  if (criteria.length === 0) return null;

  const doneByGoal = new Map<string, { done: number; total: number }>();
  const goalOfTask = new Map(view.tasks.map((k) => [k.id, k.weekly_goal_id]));
  for (const t of view.tickets) {
    const goalId = t.task_id ? goalOfTask.get(t.task_id) : null;
    if (!goalId) continue;
    const acc = doneByGoal.get(goalId) ?? { done: 0, total: 0 };
    acc.total += 1;
    if (t.status === "resolved") acc.done += 1;
    doneByGoal.set(goalId, acc);
  }

  return (
    <section className="blueprint">
      <h5>완성 청사진</h5>
      {view.project.blueprint?.summary && (
        <p className="summary">{view.project.blueprint.summary}</p>
      )}
      <ul>
        {criteria.map((c) => {
          const owners = view.weekly_goals.filter((g) => g.covers?.includes(c.key));
          const counts = owners.map((g) => doneByGoal.get(g.id) ?? { done: 0, total: 0 });
          const done = counts.reduce((n, x) => n + x.done, 0);
          const total = counts.reduce((n, x) => n + x.total, 0);
          const complete = total > 0 && done === total;
          return (
            <li key={c.key} className={complete ? "met" : ""}>
              <span className="mark" aria-hidden>
                {complete ? "●" : "○"}
              </span>
              <div>
                <p className="text">{c.text}</p>
                <p className="owner">
                  {owners.length === 0 ? (
                    <span className="risk">맡은 주 없음 — 확인이 필요합니다</span>
                  ) : (
                    <>
                      {owners.map((g) => `${g.week_index}주차`).join(" · ")}
                      {total > 0 && ` · 티켓 ${done}/${total}`}
                    </>
                  )}
                </p>
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
