"""The shared OpenAI chat client for structured LLM calls (RULES §8), and its process-wide slot.

Answers are parsed into a Pydantic model by the SDK's structured outputs, never from free text.
Nothing here logs prompts or answers.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import httpx2
import openai
from openai.types.chat import ChatCompletionMessageParam
from pydantic import BaseModel, ValidationError

from app.core.config import OPENAI_BASE_URL, get_settings

# Interactive calls: one attempt, so a slow answer fails fast and is still metered as failed.
# A non-streamed answer sends nothing until it is complete, and ranking 100 profiles is slow.
TIMEOUT_SECONDS = 180.0


class LLMError(Exception):
    """The call failed. The billed token counts are set when the provider answered (and billed)
    anyway; input and output are kept apart because output tokens cost six times more."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        billed_tokens: int | None = None,
        billed_output_tokens: int | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.billed_tokens = billed_tokens
        self.billed_output_tokens = billed_output_tokens


class LLMConfigurationError(LLMError):
    """No usable OPENAI_API_KEY."""


@dataclass(frozen=True)
class LLMResult[T]:
    parsed: T
    input_tokens: int
    output_tokens: int


class OpenAIChatClient:
    provider_name = "openai"

    def __init__(self, *, api_key: str, http_client: httpx2.AsyncClient | None = None) -> None:
        self._client = openai.AsyncOpenAI(
            api_key=api_key,
            base_url=OPENAI_BASE_URL,
            max_retries=0,
            timeout=TIMEOUT_SECONDS,
            http_client=http_client,
        )

    async def parse[T: BaseModel](
        self,
        *,
        model: str,
        instructions: str,
        content: str,
        schema: type[T],
        max_output_tokens: int,
        on_text: Callable[[str], Awaitable[None]] | None = None,
    ) -> LLMResult[T]:
        """With `on_text`, the answer is streamed and `on_text` gets the text so far after each
        piece, so a caller can show progress; the result is the same either way."""
        messages: list[ChatCompletionMessageParam] = [
            {"role": "system", "content": instructions},
            {"role": "user", "content": content},
        ]
        try:
            if on_text is None:
                completion = await self._client.chat.completions.parse(
                    model=model,
                    messages=messages,
                    response_format=schema,
                    max_completion_tokens=max_output_tokens,
                    # gpt-5.4 models accept none/low/medium/high/xhigh; low keeps judgement cheap.
                    reasoning_effort="low",
                )
            else:
                async with self._client.chat.completions.stream(
                    model=model,
                    messages=messages,
                    response_format=schema,
                    max_completion_tokens=max_output_tokens,
                    reasoning_effort="low",
                    # Without this a streamed answer reports no token usage, so it can't be priced.
                    stream_options={"include_usage": True},
                ) as stream:
                    async for event in stream:
                        if event.type == "content.delta":
                            await on_text(event.snapshot)
                    completion = await stream.get_final_completion()
        except openai.APIStatusError as exc:
            raise LLMError(type(exc).__name__, status_code=exc.status_code) from exc
        except openai.OpenAIError as exc:
            # Includes LengthFinishReasonError: the answer was cut off at max_output_tokens.
            raise LLMError(type(exc).__name__) from exc
        except (ValueError, ValidationError) as exc:
            raise LLMError("malformed provider response") from exc
        usage = completion.usage
        input_tokens = usage.prompt_tokens if usage else 0
        output_tokens = usage.completion_tokens if usage else 0
        parsed = completion.choices[0].message.parsed if completion.choices else None
        if parsed is None:  # a refusal
            raise LLMError(
                "no structured answer",
                billed_tokens=input_tokens,
                billed_output_tokens=output_tokens,
            )
        return LLMResult(parsed, input_tokens, output_tokens)

    async def aclose(self) -> None:
        await self._client.close()


_installed_client: OpenAIChatClient | None = None


def get_llm_client() -> OpenAIChatClient:
    global _installed_client
    if _installed_client is None:
        api_key = get_settings().usable_openai_api_key()
        if api_key is None:
            raise LLMConfigurationError("LLM calls require a real OPENAI_API_KEY to be set.")
        _installed_client = OpenAIChatClient(api_key=api_key)
    return _installed_client


def use_llm_client(client: OpenAIChatClient | None) -> None:
    """Install a client (tests) or clear the slot, without closing what was there."""
    global _installed_client
    _installed_client = client
