"""환경 설정. SPEC §3.1 스택 기준."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# .env 는 레포 루트에 둔다. 백엔드는 backend/ 에서 실행되므로 상대 경로로는 못 찾는다.
_REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(_REPO_ROOT / ".env", Path(".env")), extra="ignore"
    )

    # Supabase(PostgreSQL) 연결 문자열. 로컬 개발 시 일반 Postgres 도 그대로 쓴다.
    database_url: str = "postgresql://postgres:postgres@localhost:5432/roadmap_planner"

    # LLM (SPEC §3.1). 진단·재설계·분해에만 쓴다. 감지에는 절대 쓰지 않는다 (R2).
    anthropic_api_key: str | None = None
    llm_model: str = "claude-sonnet-5"
    llm_max_tokens: int = 16000
    # API 키 없이 데모·개발할 때. 그래프는 그대로 돌고 LLM 만 목업으로 바뀐다.
    use_mock_planner: bool = False

    # SPEC §3.3 — critic 실패 시 decompose 재시도 상한
    critic_max_retries: int = 3

    # SPEC §0.3 — 로그인은 자를 수 있는 항목. v1 은 데모 계정 고정.
    demo_user_id: str = "00000000-0000-0000-0000-000000000001"

    scheduler_enabled: bool = True
    cors_origins: str = "http://localhost:5173"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


    @property
    def has_real_api_key(self) -> bool:
        """자리표시자를 진짜 키로 착각하지 않는다.

        .env.example 을 그대로 복사하면 sk-ant-... 같은 문자열이 들어오는데,
        이걸 키로 믿고 실제 클라이언트를 만들면 "로드맵 만들기"를 누르는 순간
        401 로 죽는다. 로컬에서 처음 돌려보는 사람이 가장 먼저 밟는 지점이다.
        """
        key = (self.anthropic_api_key or "").strip()
        return len(key) > 20 and "..." not in key


@lru_cache
def get_settings() -> Settings:
    return Settings()
