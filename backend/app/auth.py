"""로그인 (SPEC §0.3 개정 — 데모 계정 고정에서 구글 로그인으로).

하는 일은 둘이다.
  * 구글이 준 ID 토큰이 진짜인지 확인하고, 그 계정을 users 한 행으로 옮긴다.
  * 그 뒤로는 서명된 세션 쿠키 하나로 사용자를 알아본다.

새 기술을 들이지 않는다 (R6). ID 토큰 검증은 구글의 tokeninfo 엔드포인트에
맡기고 — 로그인 한 번에 한 번 부르는 호출이다 — 쿠키 서명은 stdlib hmac 으로 한다.
JWT 라이브러리도, 세션 저장소도 들지 않는다.

세션이 서버에 없다는 것은 로그아웃이 쿠키를 지우는 것뿐이라는 뜻이다. 이미 나간
쿠키는 만료까지 유효하다. 계정을 강제로 끊어야 하면 SESSION_SECRET 을 바꾼다.
"""

import base64
import hashlib
import hmac
import json
import logging
import secrets
import time
import uuid
from dataclasses import dataclass

import asyncpg
import httpx
from fastapi import HTTPException, Request, Response

from app import db
from app.config import get_settings

log = logging.getLogger(__name__)

SESSION_COOKIE = "rp_session"

_TOKENINFO_URL = "https://oauth2.googleapis.com/tokeninfo"
_GOOGLE_ISSUERS = {"accounts.google.com", "https://accounts.google.com"}

# SESSION_SECRET 이 없을 때만 쓰는 임시 키. 프로세스가 살아 있는 동안만 유효하다.
_runtime_secret: str | None = None


def _secret() -> bytes:
    global _runtime_secret
    configured = (get_settings().session_secret or "").strip()
    if configured:
        return configured.encode()
    if _runtime_secret is None:
        _runtime_secret = secrets.token_urlsafe(32)
        log.warning(
            "SESSION_SECRET 이 없다. 임시 키로 서명한다 — 재시작하면 로그인이 전부 풀린다."
        )
    return _runtime_secret.encode()


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _b64d(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _sign(body: str) -> str:
    return _b64e(hmac.new(_secret(), body.encode(), hashlib.sha256).digest())


# ─────────────────────────────────────────────────────────────
# 세션 쿠키
# ─────────────────────────────────────────────────────────────


def issue_session(user_id: uuid.UUID | str) -> str:
    """`<payload>.<서명>`. payload 는 숨기는 값이 아니라 위조만 막으면 되는 값이다."""
    settings = get_settings()
    payload = {
        "uid": str(user_id),
        "exp": int(time.time()) + settings.session_max_age_days * 86400,
    }
    body = _b64e(json.dumps(payload, separators=(",", ":")).encode())
    return f"{body}.{_sign(body)}"


def read_session(token: str | None) -> str | None:
    """쿠키에서 user_id 를 꺼낸다. 위조·만료·손상은 전부 None 이다."""
    if not token or token.count(".") != 1:
        return None
    # ⚠ compare_digest 는 ASCII 아닌 str 을 받으면 TypeError 를 던진다. 쿠키 값은
    # 남이 채워 보내는 자리라, 한글 한 글자만 넣어도 500 이 나는 문이 된다.
    if not token.isascii():
        return None
    body, signature = token.split(".")
    # 서명 비교는 compare_digest 로 한다 — 앞자리부터 틀린 위치를 시간으로 알려주지 않는다.
    if not hmac.compare_digest(signature, _sign(body)):
        return None
    try:
        payload = json.loads(_b64d(body))
    except (ValueError, json.JSONDecodeError):
        return None
    if payload.get("exp", 0) < time.time():
        return None
    uid = payload.get("uid")
    return uid if isinstance(uid, str) else None


def set_session_cookie(response: Response, user_id: uuid.UUID | str) -> None:
    settings = get_settings()
    response.set_cookie(
        SESSION_COOKIE,
        issue_session(user_id),
        max_age=settings.session_max_age_days * 86400,
        # 자바스크립트가 못 읽는다. XSS 가 나도 세션은 안 새어 나간다.
        httponly=True,
        # 프론트(:5173)와 백엔드(:8000)는 포트만 다르므로 같은 사이트다 — lax 로 실린다.
        # 다른 도메인에 배포할 거면 samesite="none" 과 secure=True 가 함께 필요하다.
        samesite="lax",
        secure=settings.session_cookie_secure,
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")


# ─────────────────────────────────────────────────────────────
# 구글 ID 토큰
# ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class GoogleIdentity:
    sub: str
    email: str
    display_name: str | None
    avatar_url: str | None


async def verify_google_id_token(id_token: str) -> GoogleIdentity:
    """구글이 발급한 ID 토큰인지 확인하고 계정 정보를 꺼낸다."""
    settings = get_settings()
    if not settings.google_login_enabled:
        raise HTTPException(503, "구글 로그인이 설정돼 있지 않다.")

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            res = await client.get(_TOKENINFO_URL, params={"id_token": id_token})
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"구글에 확인하지 못했다: {exc}") from exc

    if res.status_code != 200:
        # 서명이 틀렸거나 만료됐거나 토큰이 아니다. 구글이 전부 여기서 걸러 준다.
        raise HTTPException(401, "구글이 이 토큰을 인정하지 않는다.")
    claims = res.json()

    # ⚠ tokeninfo 는 서명과 만료는 봐 주지만 "이 토큰이 우리 앱을 향한 것인가"는
    # 봐 주지 않는다. aud 를 여기서 직접 확인하지 않으면, 아무 구글 앱에서나 받은
    # 토큰을 들고 와도 우리 쪽 계정으로 들어올 수 있다.
    if claims.get("aud") != (settings.google_client_id or "").strip():
        raise HTTPException(401, "다른 앱에 발급된 토큰이다.")
    if claims.get("iss") not in _GOOGLE_ISSUERS:
        raise HTTPException(401, "구글이 발급한 토큰이 아니다.")
    # tokeninfo 의 불리언은 문자열로 온다.
    if str(claims.get("email_verified", "")).lower() != "true":
        raise HTTPException(403, "이메일이 확인되지 않은 구글 계정이다.")
    email = claims.get("email")
    sub = claims.get("sub")
    if not email or not sub:
        raise HTTPException(400, "계정을 식별할 수 없는 토큰이다.")

    return GoogleIdentity(
        sub=sub,
        email=email,
        display_name=claims.get("name"),
        avatar_url=claims.get("picture"),
    )


async def upsert_user(conn: asyncpg.Connection, identity: GoogleIdentity) -> asyncpg.Record:
    """구글 계정 하나를 users 한 행으로. 키는 sub 이다 (이메일은 바뀔 수 있다).

    sub 은 없는데 이메일이 같은 행이 있으면 그 행에 sub 을 붙인다. 데모 계정처럼
    손으로 넣은 행이 이메일 unique 제약에 걸려 로그인을 통째로 막는 것을 피한다.
    """
    existing = await conn.fetchrow("select * from users where google_sub = $1", identity.sub)
    if existing is None:
        existing = await conn.fetchrow("select * from users where email = $1", identity.email)

    if existing is None:
        return await conn.fetchrow(
            """
            insert into users (google_sub, email, display_name, avatar_url, last_login_at)
            values ($1, $2, $3, $4, now())
            returning *
            """,
            identity.sub,
            identity.email,
            identity.display_name,
            identity.avatar_url,
        )

    return await conn.fetchrow(
        """
        update users
           set google_sub = $2, email = $3,
               display_name = coalesce($4, display_name),
               avatar_url = coalesce($5, avatar_url),
               last_login_at = now()
         where id = $1
        returning *
        """,
        existing["id"],
        identity.sub,
        identity.email,
        identity.display_name,
        identity.avatar_url,
    )


# ─────────────────────────────────────────────────────────────
# 의존성
# ─────────────────────────────────────────────────────────────


async def current_user(request: Request) -> asyncpg.Record:
    """로그인한 사용자. 없으면 401."""
    user_id = read_session(request.cookies.get(SESSION_COOKIE))
    if user_id is None:
        raise HTTPException(401, "로그인이 필요하다.")
    try:
        parsed = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(401, "세션이 깨졌다.") from None
    async with db.acquire() as conn:
        user = await conn.fetchrow("select * from users where id = $1", parsed)
    if user is None:
        # 서명은 맞는데 계정이 없다 — 지워진 계정의 오래된 쿠키다.
        raise HTTPException(401, "없는 계정이다.")
    return user


async def assert_owns_project(
    conn: asyncpg.Connection, project_id: uuid.UUID, user: asyncpg.Record
) -> None:
    """남의 프로젝트에는 403 이 아니라 404 를 준다.

    403 은 "그 id 는 실재한다"를 알려주는 답이다. 남의 로드맵이 있는지 없는지는
    알려 줄 이유가 없다.
    """
    owner = await conn.fetchval("select user_id from projects where id = $1", project_id)
    if owner is None or owner != user["id"]:
        raise HTTPException(404, "없는 프로젝트다.")
