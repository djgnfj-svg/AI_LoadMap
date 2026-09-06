"""LLM 호출 경계면.

이 파일 바깥에서 Anthropic SDK 를 직접 부르지 않는다. 이유 두 가지:
  * 테스트에서 가짜 구현을 끼워 넣어 API 키 없이 그래프 전체를 돌린다.
  * SPEC R2 — 감지에는 AI 가 개입하지 않는다. LLM 이 닿는 지점을 한 파일로 좁혀 둔다.
"""

from typing import Protocol, TypeVar

from pydantic import BaseModel

from app.config import get_settings

T = TypeVar("T", bound=BaseModel)


class Planner(Protocol):
    """구조화 출력 한 번을 뽑는 최소 인터페이스."""

    async def structured(self, *, system: str, prompt: str, output_model: type[T]) -> T: ...


class AnthropicPlanner:
    """Claude 구조화 출력 (SPEC §3.1 — 구조화 출력 안정성 때문에 고른 스택)."""

    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        from anthropic import AsyncAnthropic

        settings = get_settings()
        key = api_key or settings.anthropic_api_key
        if not key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY 가 없다. .env 를 채우거나 Planner 를 주입해라."
            )
        self._client = AsyncAnthropic(api_key=key)
        self._model = model or settings.llm_model
        self._max_tokens = settings.llm_max_tokens

    async def structured(self, *, system: str, prompt: str, output_model: type[T]) -> T:
        response = await self._client.messages.parse(
            model=self._model,
            max_tokens=self._max_tokens,
            system=system,
            thinking={"type": "adaptive"},
            messages=[{"role": "user", "content": prompt}],
            output_format=output_model,
        )
        parsed = response.parsed_output
        if parsed is None:
            raise RuntimeError(f"{output_model.__name__} 파싱 실패: {response.stop_reason}")
        return parsed
