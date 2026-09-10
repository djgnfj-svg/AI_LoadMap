/** 만들다 생긴 일을 던지는 자리 (SPEC §3.7).
 *
 * 계획을 세워 주는 도구는 많다. 계획대로 안 될 때 얽힌 것을 풀어 주는 것이
 * 이 제품의 주장이고, 그 주장이 사는 화면이 여기다.
 *
 * 제목 한 줄을 받아 **어디에 놓이고 무엇 다음인지**를 내밀고, 승인은 사용자가 한다.
 * 청사진 확정·재설계 diff 와 같은 결이다 — AI 가 계획을 말없이 바꾸지 않는다.
 */
import { useState } from "react";

import { placementApi, type PlacementDiff } from "../api";

interface Props {
  projectId: string;
  /** 적용 뒤 계획을 다시 읽는다. */
  onApplied: () => void;
}

const TYPE_LABEL: Record<string, string> = {
  add_ticket: "티켓 추가",
  add_dependency: "순서",
};

export function AddTicket({ projectId, onApplied }: Props) {
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState("");
  const [session, setSession] = useState<string | null>(null);
  const [diff, setDiff] = useState<PlacementDiff | null>(null);
  const [approved, setApproved] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const reset = () => {
    setOpen(false);
    setTitle("");
    setSession(null);
    setDiff(null);
    setApproved(new Set());
    setError(null);
  };

  const place = async () => {
    setBusy(true);
    setError(null);
    try {
      const res = await placementApi.place(projectId, title.trim());
      setSession(res.session_id);
      setDiff(res.diff);
      // 기본은 전부 승인이다. 빼는 쪽이 사용자의 일이 된다.
      setApproved(new Set(res.diff.changes.map((c) => c.id)));
    } catch (e) {
      setError(e instanceof Error ? e.message : "자리를 못 찾았습니다.");
    } finally {
      setBusy(false);
    }
  };

  const apply = async () => {
    if (!session) return;
    setBusy(true);
    try {
      await placementApi.apply(projectId, session, [...approved]);
      reset();
      onApplied();
    } catch (e) {
      setError(e instanceof Error ? e.message : "적용하지 못했습니다.");
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

  if (!open) {
    return (
      <button className="ghost add-ticket-open" onClick={() => setOpen(true)}>
        + 할 일 추가
      </button>
    );
  }

  return (
    <section className="add-ticket">
      {!diff && (
        <>
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && title.trim().length >= 2 && !busy) void place();
            }}
            placeholder="새로 생긴 일"
            disabled={busy}
            autoFocus
          />
          <div className="actions">
            <button className="ghost" onClick={reset} disabled={busy}>
              취소
            </button>
            <button
              className="primary"
              onClick={() => void place()}
              disabled={title.trim().length < 2 || busy}
            >
              {busy ? "자리 찾는 중…" : "자리 찾기"}
            </button>
          </div>
        </>
      )}

      {diff && (
        <>
          <h5>{diff.placement}</h5>
          <p className="sub">{diff.reason}</p>

          {diff.residual_violations.length > 0 && (
            <ul className="violations">
              {diff.residual_violations.map((v, i) => (
                <li key={i}>{v.message}</li>
              ))}
            </ul>
          )}

          {diff.changes.map((c) => (
            <label
              key={c.id}
              className={`change ${approved.has(c.id) ? "approved" : "rejected"}`}
            >
              <input
                type="checkbox"
                checked={approved.has(c.id)}
                onChange={() => toggle(c.id)}
              />
              <span className="type">{TYPE_LABEL[c.type] ?? c.type}</span>
              <b>{c.label}</b>
            </label>
          ))}

          <div className="actions">
            <button className="ghost" onClick={reset} disabled={busy}>
              취소
            </button>
            <button className="primary" onClick={() => void apply()} disabled={busy}>
              {busy ? "넣는 중…" : `${approved.size}건 적용`}
            </button>
          </div>
          <span className="hint">체크를 풀면 그 항목은 안 들어갑니다.</span>
        </>
      )}

      {error && <p className="error">{error}</p>}
    </section>
  );
}
