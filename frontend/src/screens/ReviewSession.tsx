/** 재점검 세션 (SPEC §2.4, §5 — 데모 하이라이트).
 *
 * 화면 순서가 곧 신뢰의 순서다.
 *   ① 집계 숫자 (AI 아님)  ② 진단 (AI)  ③ diff 좌우 비교  ④ 항목별 승인
 *
 * 숫자를 먼저 보여주는 이유: 그 다음에 오는 AI 판단의 근거가 사용자의 실제 기록임을
 * 화면에서 확인할 수 있어야 하기 때문이다 (§6.4).
 */
import { useCallback, useEffect, useState } from "react";

import { reviewsApi, type ReplanDiff, type ReviewView } from "../api";

interface Props {
  reviewDayId: string;
  onBack: () => void;
  onApplied: () => void;
}

const TYPE_LABEL: Record<string, string> = {
  split_ticket: "재분할",
  add_ticket: "티켓 추가",
  reduce_ticket: "범위 축소",
  drop_ticket: "제외",
  add_dependency: "순서",
  shift_milestone: "일정 이월",
};

export function ReviewSession({ reviewDayId, onBack, onApplied }: Props) {
  const [view, setView] = useState<ReviewView | null>(null);
  const [diff, setDiff] = useState<ReplanDiff | null>(null);
  const [approved, setApproved] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [applied, setApplied] = useState<string[] | null>(null);

  const load = useCallback(async () => {
    try {
      const data = await reviewsApi.get(reviewDayId);
      setView(data);
      if (data.session) {
        setDiff(data.session.diff);
        setApproved(new Set(data.session.diff.changes.map((c) => c.id)));
        if (data.session.applied) setApplied([]);
      }
    } catch (e) {
      setError(String(e));
    }
  }, [reviewDayId]);

  useEffect(() => {
    // setState 는 await 뒤에서 일어난다. 서버에서 세션을 읽어오는 외부 동기화라 effect 가 맞다.
    // oxlint-disable-next-line react/set-state-in-effect
    void load();
  }, [load]);

  const run = async () => {
    setBusy(true);
    setError(null);
    try {
      const res = await reviewsApi.run(reviewDayId);
      setDiff(res.diff);
      setApproved(new Set(res.diff.changes.map((c) => c.id)));
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  const apply = async () => {
    setBusy(true);
    try {
      const res = await reviewsApi.apply(reviewDayId, [...approved]);
      setApplied(res.applied);
      onApplied();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  const toggle = (id: string) => {
    const next = new Set(approved);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setApproved(next);
  };

  if (error) return <div className="empty">불러오지 못했습니다: {error}</div>;
  if (!view) return <div className="empty">불러오는 중…</div>;

  const s = view.signals;
  const done = applied !== null;

  return (
    <div className="review-screen">
      <div className="topbar">
        <button onClick={onBack}>←</button>
        <h2>재점검 · {s.node_label}</h2>
        <span className="goal">{view.review_day.trigger_reason}</span>
        <span className="stat">{view.review_day.scheduled_date}</span>
      </div>

      <div className="review-body">
        {/* ① 집계 — AI 아님, 숫자 */}
        <section className="review-step">
          <h4>
            <span className="step-no">1</span> 무슨 일이 있었나
            <span className="tag">SQL 집계 · AI 미개입</span>
          </h4>
          <div className="stat-grid">
            <div>
              <b>
                {s.done_tickets}/{s.total_tickets}
              </b>
              <span>완료</span>
            </div>
            <div>
              <b className="risk">{s.delayed_tickets}</b>
              <span>지연된 티켓</span>
            </div>
            <div>
              <b>{s.missed_count}</b>
              <span>마감 놓침</span>
            </div>
            <div>
              <b>{s.deferred_count}</b>
              <span>직접 미룸</span>
            </div>
            <div>
              <b>{s.avg_delay_days}일</b>
              <span>평균 지연</span>
            </div>
          </div>
          {s.blocked_reasons.length > 0 && (
            <>
              <h5>직접 적은 막힘 사유</h5>
              <ul className="reasons">
                {s.blocked_reasons.map((r, i) => (
                  <li key={i}>{r}</li>
                ))}
              </ul>
            </>
          )}
        </section>

        {/* ② 진단 — 여기서부터 AI */}
        <section className="review-step">
          <h4>
            <span className="step-no">2</span> 왜 막혔나
            <span className="tag ai">AI 진단</span>
          </h4>
          {!diff && (
            <>
              <p className="sub">
                위 숫자를 근거로 진단하고, 막힌 구간만 다시 설계합니다. 범위는 마일스톤 1개입니다.
              </p>
              <button className="primary" onClick={run} disabled={busy}>
                {busy ? "재설계 중…" : "재설계 실행"}
              </button>
            </>
          )}
          {diff && (
            <div className="diagnosis">
              <span className="badge">{diff.diagnosis}</span>
              <p>{diff.rationale}</p>
            </div>
          )}
        </section>

        {/* ③④ diff 좌우 비교 + 항목별 승인 */}
        {diff && (
          <section className="review-step">
            <h4>
              <span className="step-no">3</span> 무엇을 바꿀까
              <span className="tag">범위: {diff.scope_milestone_title}</span>
            </h4>

            {diff.residual_violations.length > 0 && (
              <div className="notice warn">
                <h4>검증에 남은 항목</h4>
                <ul>
                  {diff.residual_violations.map((v, i) => (
                    <li key={i}>{v.message}</li>
                  ))}
                </ul>
              </div>
            )}

            {diff.changes.length === 0 && (
              <div className="sub">바꿀 것을 찾지 못했습니다.</div>
            )}

            {diff.changes.map((c) => (
              <div
                className={`change ${approved.has(c.id) ? "approved" : "rejected"}`}
                key={c.id}
              >
                <div className="change-head">
                  <label>
                    <input
                      type="checkbox"
                      checked={approved.has(c.id)}
                      disabled={done}
                      onChange={() => toggle(c.id)}
                    />
                    <span className="type">{TYPE_LABEL[c.type] ?? c.type}</span>
                    <b>{c.label}</b>
                  </label>
                </div>
                <div className="change-diff">
                  <div className="before">
                    <span>전</span>
                    <p>{c.before ?? "(없음)"}</p>
                  </div>
                  <div className="after">
                    <span>후</span>
                    <p>{c.after ?? "(제거)"}</p>
                  </div>
                </div>
                <div className="sub">{c.reason}</div>
              </div>
            ))}

            {!done && diff.changes.length > 0 && (
              <div className="actions">
                <button className="primary" onClick={apply} disabled={busy}>
                  승인한 {approved.size}건 적용
                </button>
                <span className="sub">
                  체크를 풀면 그 항목은 적용되지 않습니다.
                </span>
              </div>
            )}
            {done && (
              <div className="notice">
                <h4>적용됐습니다</h4>
                <div className="sub">
                  로드맵과 다이어그램에 반영됐습니다.{" "}
                  <button className="link-btn" onClick={onBack}>
                    돌아가서 보기
                  </button>
                </div>
              </div>
            )}
          </section>
        )}
      </div>
    </div>
  );
}
