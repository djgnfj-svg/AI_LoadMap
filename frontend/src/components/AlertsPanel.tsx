/** 알람 목록 (SPEC §5). 문구 톤은 R5 — 책망이 아니라 진단. */
import { useCallback, useEffect, useState } from "react";

import { alertsApi, type Alert, type ReviewDay } from "../api";

interface Props {
  projectId: string;
  onClose: () => void;
  onOpenReview: (reviewDayId: string) => void;
  onChanged: () => void;
}

const SEVERITY_LABEL: Record<Alert["severity"], string> = {
  high: "높음",
  medium: "중간",
  low: "낮음",
};

export function AlertsPanel({ projectId, onClose, onOpenReview, onChanged }: Props) {
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [reviews, setReviews] = useState<ReviewDay[]>([]);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    const data = await alertsApi.list(projectId);
    setAlerts(data.alerts);
    setReviews(data.review_days);
  }, [projectId]);

  useEffect(() => {
    // oxlint-disable-next-line react/set-state-in-effect
    void load();
  }, [load]);

  const detect = async () => {
    setBusy(true);
    try {
      await alertsApi.detect(projectId);
      await load();
      onChanged();
    } finally {
      setBusy(false);
    }
  };

  const ack = async (id: string) => {
    await alertsApi.ack(id);
    await load();
  };

  return (
    <aside className="detail">
      <header>
        <h3>알람</h3>
        <button onClick={onClose} aria-label="닫기">
          ✕
        </button>
      </header>
      <div className="sub">
        마감·지연·무활동은 전부 기록에서 SQL 로 계산합니다. AI 는 여기 개입하지 않습니다.
      </div>

      <div className="actions">
        <button onClick={detect} disabled={busy}>
          {busy ? "확인 중…" : "지금 감지 돌리기"}
        </button>
      </div>

      {reviews.length > 0 && (
        <section>
          <h5>잡힌 재점검일</h5>
          {reviews.map((r) => (
            <div className="review-card" key={r.id}>
              <div>
                <b>{r.scheduled_date}</b> · {r.node_label ?? "전체"}
              </div>
              <div className="sub">{r.trigger_reason}</div>
              {r.postponed_count > 0 && (
                <div className="sub">{r.postponed_count}번 미룸</div>
              )}
              <button className="primary" onClick={() => onOpenReview(r.id)}>
                재점검 세션 열기
              </button>
            </div>
          ))}
        </section>
      )}

      <section>
        <h5>미확인 알람 {alerts.length}건</h5>
        {alerts.length === 0 && <div className="sub">지금은 걸리는 게 없습니다.</div>}
        {alerts.map((a) => (
          <div className={`alert-card ${a.severity}`} key={a.id}>
            <div className="alert-head">
              <span className={`sev ${a.severity}`}>{SEVERITY_LABEL[a.severity]}</span>
              <button className="link-btn" onClick={() => void ack(a.id)}>
                확인
              </button>
            </div>
            <div>{a.message}</div>
            {a.review_day_id && a.review_status === "scheduled" && (
              <button
                className="link-btn"
                onClick={() => onOpenReview(a.review_day_id as string)}
              >
                재점검 세션 열기 →
              </button>
            )}
          </div>
        ))}
      </section>
    </aside>
  );
}
