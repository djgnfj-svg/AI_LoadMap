"""환경 설정. SPEC §3.1 스택 기준."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Supabase(PostgreSQL) 연결 문자열. 로컬 개발 시 일반 Postgres 도 그대로 쓴다.
    database_url: str = "postgresql://postgres:postgres@localhost:5432/roadmap_planner"

    # LLM (SPEC §3.1). 진단·재설계·분해에만 쓴다. 감지에는 절대 쓰지 않는다 (R2).
    anthropic_api_key: str | None = None
    llm_model: str = "claude-sonnet-5"
    llm_max_tokens: int = 16000

    # SPEC §3.3 — critic 실패 시 decompose 재시도 상한
    critic_max_retries: int = 3

    # SPEC §0.3 — 로그인은 자를 수 있는 항목. v1 은 데모 계정 고정.
    demo_user_id: str = "00000000-0000-0000-0000-000000000001"

    scheduler_enabled: bool = True
    cors_origins: str = "http://localhost:5173"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
