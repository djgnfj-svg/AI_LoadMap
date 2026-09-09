"""로그인 API.

로그인 방식이 둘로 갈린다. GOOGLE_CLIENT_ID 가 있으면 구글이고, 없으면 데모
계정이다 — API 키가 없으면 목업 Planner 로 도는 것과 같은 결이다. 클론 받아
바로 돌려보는 사람이 구글 콘솔부터 열어야 하는 상황을 만들지 않는다.

프론트는 /auth/config 를 먼저 보고 어느 버튼을 그릴지 정한다.
"""

import logging
import uuid

from fastapi import APIRouter, HTTPException, Request, Response

from app import auth, db
from app.config import get_settings
from app.models.schemas import GoogleLoginRequest

log = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


def _public(user) -> dict:  # noqa: ANN001
    """화면에 그릴 것만. google_sub 은 내보내지 않는다."""
    return {
        "id": str(user["id"]),
        "email": user["email"],
        "display_name": user["display_name"],
        "avatar_url": user["avatar_url"],
    }


@router.get("/config")
async def config() -> dict:
    """프론트가 로그인 버튼을 고르는 데 필요한 것만."""
    settings = get_settings()
    enabled = settings.google_login_enabled
    return {
        "google_enabled": enabled,
        # 구글 버튼을 그리려면 프론트도 클라이언트 ID 를 알아야 한다. 공개값이다.
        "google_client_id": (settings.google_client_id or "").strip() if enabled else None,
        "demo_login": not enabled,
    }


@router.get("/me")
async def me(request: Request) -> dict:
    """현재 로그인 상태.

    로그인 안 된 것은 오류가 아니라 답이다 — 첫 화면이 매번 401 을 밟게 하지 않는다.
    """
    user_id = auth.read_session(request.cookies.get(auth.SESSION_COOKIE))
    if user_id is None:
        return {"user": None}
    async with db.acquire() as conn:
        user = await conn.fetchrow("select * from users where id = $1", uuid.UUID(user_id))
    return {"user": _public(user) if user else None}


@router.post("/google")
async def google_login(req: GoogleLoginRequest, response: Response) -> dict:
    """구글 ID 토큰 -> 세션 쿠키."""
    identity = await auth.verify_google_id_token(req.id_token)
    async with db.transaction() as conn:
        user = await auth.upsert_user(conn, identity)
    auth.set_session_cookie(response, user["id"])
    log.info("로그인: %s", user["email"])
    return {"user": _public(user)}


@router.post("/demo")
async def demo_login(response: Response) -> dict:
    """구글이 설정돼 있지 않을 때만 열리는 문.

    ⚠ 구글 클라이언트 ID 가 들어오는 순간 이 문은 닫힌다. 배포한 곳에서 아무나
    데모 계정으로 남의 화면에 들어오는 것을 막는다.
    """
    settings = get_settings()
    if settings.google_login_enabled:
        raise HTTPException(404, "데모 로그인은 꺼져 있다.")

    async with db.acquire() as conn:
        user = await conn.fetchrow(
            "select * from users where id = $1", uuid.UUID(settings.demo_user_id)
        )
    if user is None:
        raise HTTPException(500, "데모 계정이 없다. 0004 마이그레이션을 적용해라.")
    auth.set_session_cookie(response, user["id"])
    return {"user": _public(user)}


@router.post("/logout")
async def logout(response: Response) -> dict:
    """쿠키를 지운다. 서버에 세션을 안 두므로 지울 것도 이것뿐이다."""
    auth.clear_session_cookie(response)
    return {"ok": True}
