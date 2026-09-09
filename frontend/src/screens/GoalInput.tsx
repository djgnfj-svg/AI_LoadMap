/** 목표 입력 → 인터뷰 → 생성 (SPEC §5, §3.3).
 *
 * 목표 한 줄로는 계획을 못 짠다. 목표를 받은 다음 **청사진부터 되묻는다.**
 * 첫 질문이 이 제품의 첫인상이라, 그 질문은 LLM 이 아니라 코드가 고정한다
 * (backend/app/graphs/interview.py).
 *
 * 답한 것은 원문 그대로 남아 계획을 만드는 프롬프트로 들어간다. 그래서 지난 문답을
 * 화면에 계속 띄워 둔다 — 무엇을 근거로 이 계획이 나왔는지 사용자가 봐야 한다.
 *
 * 인터뷰가 끝나면 **완성 기준을 사용자가 확정한다.** AI 는 초안만 쓴다. 무엇이
 * 「끝」인지는 목표를 가진 사람만 정할 수 있고, 그걸 AI 가 정해버리면 그 뒤의
 * 계획 전체가 남의 목표가 된다.
 */
import { useCallback, useEffect, useRef, useState } from "react";

import {
  api,
  streamGeneration,
  type ClarifyQuestion,
  type InterviewTurn,
  type StepEvent,
  type SuccessCriterion,
} from "../api";
import { DOMAINS, words } from "../domain";

interface Props {
  onCreated: (projectId: string) => void;
  onBack: () => void;
  /** 인터뷰 도중 나갔던 프로젝트를 이어서 연다 (새로고침·재시작 복구). */
  resumeProjectId?: string;
}

export function GoalInput({ onCreated, onBack, resumeProjectId }: Props) {
  const [goal, setGoal] = useState("");
  const [weeks, setWeeks] = useState("");
  const [hours, setHours] = useState("");
  const [stack, setStack] = useState("");

  const [projectId, setProjectId] = useState<string | null>(resumeProjectId ?? null);
  const [steps, setSteps] = useState<StepEvent[]>([]);
  const [questions, setQuestions] = useState<ClarifyQuestion[]>([]);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [answered, setAnswered] = useState<InterviewTurn[]>([]);
  const [criteria, setCriteria] = useState<string[] | null>(null);
  const [summary, setSummary] = useState("");
  const [domain, setDomain] = useState("software");
  const [repairs, setRepairs] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const closeStream = useRef<(() => void) | null>(null);

  const openBlueprint = useCallback(
    (draft: { summary?: string; criteria?: SuccessCriterion[] }, guessed?: string | null) => {
      if (guessed) setDomain(guessed);
      setSummary(draft.summary ?? "");
      // 최소 한 줄은 비워서라도 내민다 — 직접 쓰는 자리가 보여야 한다.
      setCriteria((draft.criteria ?? []).map((c) => c.text).concat(""));
      setQuestions([]);
      setRunning(false);
    },
    [],
  );

  /** 지금까지 답한 문답과 진행 상태를 서버에서 읽어 온다. 둘 다 DB 에 있다. */
  const loadTranscript = useCallback(
    async (id: string) => {
      try {
        const view = await api.getProject(id);
        setAnswered(view.interview.filter((t) => t.answer.trim().length > 0));
        if (view.generation.status === "awaiting_clarify") {
          setQuestions(view.generation.questions);
        } else if (view.generation.status === "awaiting_blueprint") {
          openBlueprint(view.project.blueprint ?? {}, view.project.domain);
        }
      } catch {
        // 상태를 못 읽어도 답하는 것 자체는 막지 않는다.
      }
    },
    [openBlueprint],
  );

  const listen = (id: string) => {
    closeStream.current?.();
    closeStream.current = streamGeneration(id, {
      onStep: (e) => setSteps((prev) => [...prev, e]),
      onClarify: (qs) => {
        setQuestions(qs);
        setAnswers({});
        setRunning(false);
        void loadTranscript(id);
      },
      onBlueprint: (draft, guessed) => {
        openBlueprint(draft, guessed);
        void loadTranscript(id);
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

  useEffect(() => {
    // 이어서 열린 경우에만 서버에서 상태를 읽는다.
    // oxlint-disable-next-line react/set-state-in-effect
    if (resumeProjectId) void loadTranscript(resumeProjectId);
  }, [resumeProjectId, loadTranscript]);

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
    // 답을 비워 보낸 질문은 「건너뛰겠다」는 답이다. 서버가 같은 질문을 다시 묻지 않는다.
    const payload: Record<string, string> = {};
    for (const q of questions) payload[q.field] = answers[q.field] ?? "";
    setQuestions([]);
    try {
      await api.submitClarify(projectId, payload);
      listen(projectId);
    } catch (e) {
      setError(String(e));
      setRunning(false);
    }
  };

  const confirmBlueprint = async () => {
    if (!projectId) return;
    setRunning(true);
    setSteps([]);
    const list = (criteria ?? []).map((c) => c.trim()).filter(Boolean);
    setCriteria(null);
    try {
      await api.confirmBlueprint(projectId, summary.trim(), list, domain);
      listen(projectId);
    } catch (e) {
      setError(String(e));
      setRunning(false);
    }
  };

  const setCriterion = (i: number, text: string) =>
    setCriteria((prev) => (prev ?? []).map((c, n) => (n === i ? text : c)));

  const interviewing = questions.length > 0;
  const confirming = criteria !== null;

  return (
    <div className="goal-screen">
      <button className="ghost back" onClick={onBack}>
        ← 내 로드맵
      </button>

      {!projectId && (
        <>
          <h1>무엇을 만들 건가요?</h1>
          <p className="lede">
            한 줄로 적으면 됩니다. 자세한 건 바로 이어서 물어볼게요.
          </p>

          <textarea
            value={goal}
            onChange={(e) => setGoal(e.target.value)}
            placeholder="예: 3개월 안에 코옵 멀티플레이어 게임 하나 출시"
            disabled={running}
          />
          <div className="field-row">
            <div className="field">
              <label htmlFor="weeks">기간(주)</label>
              <input id="weeks" value={weeks} onChange={(e) => setWeeks(e.target.value)}
                placeholder="12" inputMode="numeric" disabled={running} />
            </div>
            <div className="field">
              <label htmlFor="hours">주당 가용시간</label>
              <input id="hours" value={hours} onChange={(e) => setHours(e.target.value)}
                placeholder="10" inputMode="numeric" disabled={running} />
            </div>
            <div className="field">
              <label htmlFor="stack">도구 · 스택 (쉼표로 구분)</label>
              <input id="stack" value={stack} onChange={(e) => setStack(e.target.value)}
                placeholder="unity, c# / 해커스 교재" disabled={running} />
            </div>
          </div>

          <div className="actions">
            <button className="primary" onClick={submit} disabled={goal.trim().length < 5 || running}>
              {running ? "읽는 중…" : "시작하기"}
            </button>
            <span className="hint">비워두면 목표 문장에서 추론하고, 애매하면 되묻습니다.</span>
          </div>
        </>
      )}

      {projectId && interviewing && (
        <>
          <h1>몇 가지만 물어볼게요</h1>
          <p className="lede">
            여기 적은 말이 <b>그대로</b> 계획의 근거가 됩니다. 모르는 건 비워두고 넘어가도 됩니다.
          </p>
        </>
      )}

      {projectId && confirming && (
        <>
          <h1>이렇게 되면 끝난 건가요?</h1>
          <p className="lede">
            답해주신 걸로 <b>초안</b>을 적었습니다. <b>확정은 직접 하셔야 합니다</b> — 고치고,
            지우고, 더 넣어주세요. 여기 남는 것이 계획의 기준이 됩니다.
          </p>
        </>
      )}

      {answered.length > 0 && (
        <section className="transcript">
          <h5>지금까지 답한 것</h5>
          {answered.map((t) => (
            <div className="turn" key={`${t.round}-${t.field}`}>
              <p className="q">{t.question}</p>
              <p className="a">{t.answer}</p>
            </div>
          ))}
        </section>
      )}

      {interviewing && (
        <div className="interview">
          {questions.map((q, i) => (
            <div className="clarify-q" key={q.field}>
              <label htmlFor={`q-${q.field}`}>
                <span className="q-no">{i + 1}</span>
                {q.question}
              </label>
              <textarea
                id={`q-${q.field}`}
                rows={q.field === "blueprint" ? 5 : 3}
                value={answers[q.field] ?? ""}
                onChange={(e) => setAnswers({ ...answers, [q.field]: e.target.value })}
                disabled={running}
              />
            </div>
          ))}
          <div className="actions">
            <button className="primary" onClick={sendAnswers} disabled={running}>
              {running ? "읽는 중…" : "이어서 만들기"}
            </button>
            <span className="hint">비워둔 질문은 건너뜁니다. 다시 묻지 않아요.</span>
          </div>
        </div>
      )}

      {confirming && (
        <div className="blueprint-edit">
          <div className="field">
            <label htmlFor="bp-domain">무엇을 만드는 목표인가요</label>
            <div className="domain-pick" id="bp-domain">
              {DOMAINS.map((d) => (
                <button
                  key={d}
                  className={domain === d ? "on" : ""}
                  onClick={() => setDomain(d)}
                  disabled={running}
                >
                  {words(d).label}
                </button>
              ))}
            </div>
            <span className="hint">
              고른 쪽에 맞춰 오른쪽 그림을 {words(domain).map}로 그리고, 티켓 문구도 맞춥니다.
            </span>
          </div>

          <div className="field">
            <label htmlFor="bp-summary">완성된 모습 (한 문장)</label>
            <input
              id="bp-summary"
              value={summary}
              onChange={(e) => setSummary(e.target.value)}
              placeholder="예: 친구 4명이 한 방에서 30분 미션을 끝까지 돈다"
              disabled={running}
            />
          </div>

          <h5>완성 기준</h5>
          {(criteria ?? []).map((c, i) => (
            <div className="criterion" key={i}>
              <span className="no">{i + 1}</span>
              <input
                value={c}
                onChange={(e) => setCriterion(i, e.target.value)}
                placeholder="눈으로 확인할 수 있는 상태 한 줄"
                disabled={running}
              />
              <button
                className="link-btn"
                onClick={() => setCriteria((prev) => (prev ?? []).filter((_, n) => n !== i))}
                aria-label={`${i + 1}번 기준 지우기`}
                disabled={running}
              >
                ✕
              </button>
            </div>
          ))}
          <button
            className="link-btn add"
            onClick={() => setCriteria((prev) => [...(prev ?? []), ""])}
            disabled={running}
          >
            + 기준 추가
          </button>

          <div className="actions">
            <button className="primary" onClick={confirmBlueprint} disabled={running}>
              {running ? "만드는 중…" : "이 기준으로 계획 만들기"}
            </button>
            <span className="hint">
              여기 적은 기준을 어느 주도 맡지 않으면 계획이 반려됩니다.
            </span>
          </div>
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
