from __future__ import annotations

import json
import re
from typing import Any

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover
    OpenAI = None  # type: ignore[assignment]

try:
    from anthropic import Anthropic
except ImportError:  # pragma: no cover
    Anthropic = None  # type: ignore[assignment]

from ..config import Settings


def _provider(settings: Settings) -> str:
    return str(getattr(settings, "llm_provider", "openai")).strip().lower() or "openai"


def provider_label(settings: Settings) -> str:
    return "Claude" if _provider(settings) == "anthropic" else "OpenAI"


def is_ai_configured(settings: Settings) -> bool:
    if _provider(settings) == "anthropic":
        return bool(getattr(settings, "anthropic_api_key", "") and Anthropic is not None)
    return bool(getattr(settings, "openai_api_key", "") and OpenAI is not None)


def require_ai_configured(settings: Settings) -> None:
    if is_ai_configured(settings):
        return
    if _provider(settings) == "anthropic":
        if Anthropic is None:
            raise RuntimeError("anthropic 패키지가 설치되지 않았습니다. pip install -r requirements.txt를 실행하세요.")
        raise RuntimeError("ANTHROPIC_API_KEY가 없어 Claude를 사용할 수 없습니다.")
    if OpenAI is None:
        raise RuntimeError("openai 패키지가 설치되지 않았습니다. pip install -r requirements.txt를 실행하세요.")
    raise RuntimeError("OPENAI_API_KEY가 없어 OpenAI를 사용할 수 없습니다.")


def active_model(settings: Settings) -> str:
    if _provider(settings) == "anthropic":
        return str(getattr(settings, "anthropic_model", "claude-haiku-4-5"))
    return str(getattr(settings, "openai_model", "gpt-5.6-luna"))


def create_openai_client(settings: Settings):
    require_ai_configured(settings)
    if _provider(settings) != "openai" or OpenAI is None:
        raise RuntimeError("현재 AI 공급자가 OpenAI가 아닙니다.")
    return OpenAI(api_key=settings.openai_api_key)


def create_anthropic_client(settings: Settings):
    require_ai_configured(settings)
    if _provider(settings) != "anthropic" or Anthropic is None:
        raise RuntimeError("현재 AI 공급자가 Anthropic이 아닙니다.")
    return Anthropic(api_key=settings.anthropic_api_key)


def text_from_anthropic_message(message: Any) -> str:
    return "\n".join(
        str(block.text)
        for block in message.content
        if getattr(block, "type", None) == "text" and getattr(block, "text", None)
    ).strip()


def generate_text(
    settings: Settings,
    prompt: str,
    *,
    instructions: str | None = None,
    max_tokens: int | None = None,
) -> str:
    require_ai_configured(settings)
    if _provider(settings) == "anthropic":
        client = create_anthropic_client(settings)
        response = client.messages.create(
            model=settings.anthropic_model,
            max_tokens=max_tokens or settings.anthropic_max_tokens,
            system=instructions or "",
            messages=[{"role": "user", "content": prompt}],
        )
        return text_from_anthropic_message(response)

    client = create_openai_client(settings)
    kwargs: dict[str, Any] = {
        "model": settings.openai_model,
        "input": prompt,
    }
    if instructions:
        kwargs["instructions"] = instructions
    response = client.responses.create(**kwargs)
    return (response.output_text or "").strip()


def anthropic_content_from_data_urls(text: str, data_urls: list[str]) -> list[dict[str, Any]]:
    content: list[dict[str, Any]] = [{"type": "text", "text": text}]
    for url in data_urls:
        match = re.fullmatch(r"data:(image/(?:jpeg|png|gif|webp));base64,(.+)", url, flags=re.DOTALL)
        if not match:
            continue
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": match.group(1),
                "data": match.group(2),
            },
        })
    return content


def generate_vision_text(
    settings: Settings,
    prompt: str,
    data_urls: list[str],
    *,
    max_tokens: int | None = None,
) -> str:
    require_ai_configured(settings)
    if _provider(settings) == "anthropic":
        client = create_anthropic_client(settings)
        response = client.messages.create(
            model=settings.anthropic_model,
            max_tokens=max_tokens or settings.anthropic_max_tokens,
            messages=[{
                "role": "user",
                "content": anthropic_content_from_data_urls(prompt, data_urls),
            }],
        )
        return text_from_anthropic_message(response)

    client = create_openai_client(settings)
    content: list[dict[str, Any]] = [{"type": "input_text", "text": prompt}]
    content.extend({"type": "input_image", "image_url": url} for url in data_urls)
    response = client.responses.create(
        model=settings.openai_model,
        input=[{"role": "user", "content": content}],
    )
    return (response.output_text or "").strip()


def parse_json_object(text: str) -> dict[str, Any]:
    value = text.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", value, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        value = fenced.group(1).strip()
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        start = value.find("{")
        end = value.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("AI 응답에서 JSON 객체를 찾지 못했습니다.")
        parsed = json.loads(value[start:end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("AI 응답이 JSON 객체가 아닙니다.")
    return parsed
