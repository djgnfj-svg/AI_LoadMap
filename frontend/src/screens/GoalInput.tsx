/** 목표 입력 화면 (SPEC §5). 자연어 입력 -> clarify 질문 -> 생성 진행 스트리밍. */
import { useRef, useState } from "react";

import { api, streamGeneration, type ClarifyQuestion, type StepEvent } from "../api";

interface Props {
  onCreated: (projectId: string) => void;
}

export function GoalInput({ onCreated }: Props) {
  const [goal, setGoal] = useState("");
  const [weeks, setWeeks] = useState("");
  const [hours, setHours] = useState("");
  const [stack, setStack] = useState("");

  const [projectId, setProjectId] = useState<string | null>(null);
  const [steps, setSteps] = useState<StepEvent[]>([]);
  const [questions, setQuestions] = useState<ClarifyQuestion[]>([]);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [repairs, setRepairs] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const closeStream = useRef<(() => void) | null>(null);

  const listen = (id: string) => {
    closeStream.current?.();
    closeStream.current = streamGeneration(id, {
      onStep: (e) => setSteps((prev) => [...prev, e]),
      onClarify: (qs) => {
        setQuestions(qs);
        setRunning(false);
      },
      onDone: (fixes) => {
        setRepairs(fixes);
        setRunning(false);
        onCreated(id);
      },
      onError: (message) => {
        setError(message);
        setRunning(false);
      },
    });
  };

  const submit = async () => {
    setRunning(true);
    setError(null);
    setSteps([]);
    setQuestions([]);
    try {
      const res = await api.createProject({
        goal_text: goal.trim(),
        duration_weeks: weeks ? Number(weeks) : undefined,
        hours_per_week: hours ? Number(hours) : undefined,
        stack: stack ? stack.split(",").map((s) => s.trim()).filter(Boolean) : undefined,
      });
      setProjectId(res.project_id);
      listen(res.project_id);
    } catch (e) {
      setError(String(e));
      setRunning(false);
    }
  };

  const sendAnswers = async () => {
    if (!projectId) return;
    setRunning(true);
    setSteps([]);
    setQuestions([]);
    try {
      await api.submitClarify(projectId, answers);
      listen(projectId);
    } catch (e) {
      setError(String(e));
      setRunning(false);
    }
  };

  return (
    <div className="goal-screen">
      <h1>무엇을 만들 건가요?</h1>
      <p className="lede">
        목표를 적으면 마일스톤 · 주차별 목표 · 티켓으로 쪼개고, 시스템 아키텍처를 같이 그립니다.
      </p>

      <textarea
        value={goal}
        onChange={(e) => setGoal(e.target.value)}
        placeholder="예: 3개월 안에 코옵 멀티플레이어 게임 하나 출시"
        disabled={running || !!projectId}
      />
      <div className="field-row">
        <div className="field">
          <label htmlFor="weeks">기간(주)</label>
          <input id="weeks" value={weeks} onChange={(e) => setWeeks(e.target.value)}
            placeholder="12" inputMode="numeric" disabled={running || !!projectId} />
        </div>
        <div className="field">
          <label htmlFor="hours">주당 가용시간</label>
          <input id="hours" value={hours} onChange={(e) => setHours(e.target.value)}
            placeholder="10" inputMode="numeric" disabled={running || !!projectId} />
        </div>
        <div className="field">
          <label htmlFor="stack">스택 (쉼표로 구분)</label>
          <input id="stack" value={stack} onChange={(e) => setStack(e.target.value)}
            placeholder="unity, c#" disabled={running || !!projectId} />
        </div>
      </div>

      {!projectId && (
        <div className="actions">
          <button className="primary" onClick={submit} disabled={goal.trim().length < 5 || running}>
            {running ? "생성 중…" : "로드맵 만들기"}
          </button>
          <span className="step detail">비워두면 목표 문장에서 추론하고, 애매하면 되묻습니다.</span>
        </div>
      )}

      {steps.length > 0 && (
        <div className="steps">
          {steps.map((s, i) => (
            <div
              key={i}
              className={["step", s.node === "critic" ? (s.ok ? "pass" : "fail") : ""].join(" ")}
            >
              <span className="dot" />
              <span>{s.label}</span>
              {s.node === "critic" && !s.ok && (
                <span className="detail">
                  {s.violations?.map((v) => v.code).join(", ")} → 다시 쪼갭니다
                </span>
              )}
              {s.counts && (
                <span className="step-counts">
                  {s.counts.tickets ? `티켓 ${s.counts.tickets}` : ""}
                  {s.counts.nodes ? ` · 노드 ${s.counts.nodes}` : ""}
                </span>
              )}
            </div>
          ))}
        </div>
      )}

      {questions.length > 0 && (
        <div className="notice">
          <h4>몇 가지만 확인할게요</h4>
          {questions.map((q) => (
            <div className="clarify-q" key={q.field}>
              <p>{q.question}</p>
              <input
                value={answers[q.field] ?? ""}
                onChange={(e) => setAnswers({ ...answers, [q.field]: e.target.value })}
              />
            </div>
          ))}
          <button className="primary" onClick={sendAnswers} disabled={running}>
            이어서 만들기
          </button>
        </div>
      )}

      {repairs.length > 0 && (
        <div className="notice warn">
          <h4>계획을 자동으로 손봤습니다</h4>
          <ul>
            {repairs.map((r, i) => (
              <li key={i}>{r}</li>
            ))}
          </ul>
        </div>
      )}

      {error && (
        <div className="notice error">
          <h4>생성에 실패했습니다</h4>
          <div className="sub">{error}</div>
        </div>
      )}
    </div>
  );
}
