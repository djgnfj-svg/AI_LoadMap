/** 로그인 화면.
 *
 * 버튼은 서버가 정한다 — /auth/config 가 google_enabled 면 구글 버튼이고,
 * 아니면 데모 계정 버튼이다. 클라이언트 ID 를 프론트에 박아두지 않는 이유는
 * 하나뿐인 설정 자리를 백엔드 .env 로 유지하기 위해서다.
 */
import { useEffect, useRef, useState } from "react";

import { authApi, type AuthConfig, type User } from "../api";

/** 구글 스크립트가 window 에 심는 것 중 실제로 쓰는 것만 적는다. */
declare global {
  interface Window {
    google?: {
      accounts: {
        id: {
          initialize: (options: {
            client_id: string;
            callback: (response: { credential: string }) => void;
          }) => void;
          renderButton: (parent: HTMLElement, options: Record<string, unknown>) => void;
        };
      };
    };
  }
}

const GSI_SRC = "https://accounts.google.com/gsi/client";

/** 구글 로그인 스크립트를 한 번만 붙인다. */
function loadGoogleScript(): Promise<void> {
  if (window.google?.accounts?.id) return Promise.resolve();

  return new Promise((resolve, reject) => {
    const existing = document.querySelector<HTMLScriptElement>(`script[src="${GSI_SRC}"]`);
    if (existing) {
      existing.addEventListener("load", () => resolve());
      existing.addEventListener("error", () => reject(new Error("구글 스크립트를 못 불러왔다.")));
      return;
    }
    const script = document.createElement("script");
    script.src = GSI_SRC;
    script.async = true;
    script.onload = () => resolve();
    script.onerror = () => reject(new Error("구글 스크립트를 못 불러왔다."));
    document.head.appendChild(script);
  });
}

interface Props {
  onSignedIn: (user: User) => void;
}

export function Login({ onSignedIn }: Props) {
  const [config, setConfig] = useState<AuthConfig | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const buttonSlot = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    authApi.config().then(setConfig).catch((e) => setError(String(e)));
  }, []);

  useEffect(() => {
    if (!config?.google_enabled || !config.google_client_id) return;
    let cancelled = false;

    loadGoogleScript()
      .then(() => {
        if (cancelled || !buttonSlot.current || !window.google) return;
        window.google.accounts.id.initialize({
          client_id: config.google_client_id!,
          callback: ({ credential }) => {
            setBusy(true);
            setError(null);
            authApi
              .google(credential)
              .then((res) => onSignedIn(res.user))
              .catch((e) => setError(String(e)))
              .finally(() => setBusy(false));
          },
        });
        window.google.accounts.id.renderButton(buttonSlot.current, {
          theme: "filled_black",
          size: "large",
          shape: "pill",
          text: "signin_with",
          locale: "ko",
        });
      })
      .catch((e) => setError(String(e)));

    return () => {
      cancelled = true;
    };
  }, [config, onSignedIn]);

  const demoLogin = () => {
    setBusy(true);
    setError(null);
    authApi
      .demo()
      .then((res) => onSignedIn(res.user))
      .catch((e) => setError(String(e)))
      .finally(() => setBusy(false));
  };

  return (
    <div className="login-screen">
      <h1>Roadmap Planner</h1>
      <p className="lede">
        목표를 넣으면 로드맵과 아키텍처가 함께 그려지고,
        <br />
        진행 기록에 따라 스스로 다시 그려집니다.
      </p>

      {config === null && !error && <div className="login-slot muted">준비 중…</div>}

      {config?.google_enabled && (
        <div className="login-slot" ref={buttonSlot} aria-busy={busy} />
      )}

      {config?.demo_login && (
        <div className="login-slot">
          <button className="primary" onClick={demoLogin} disabled={busy}>
            {busy ? "들어가는 중…" : "데모 계정으로 둘러보기"}
          </button>
          <p className="hint">
            서버에 <code>GOOGLE_CLIENT_ID</code> 가 없어서 데모 계정으로 엽니다.
            구글 로그인을 켜면 이 버튼은 사라집니다.
          </p>
        </div>
      )}

      {error && (
        <div className="notice error">
          <h4>로그인하지 못했습니다</h4>
          <div className="sub">{error}</div>
        </div>
      )}
    </div>
  );
}
