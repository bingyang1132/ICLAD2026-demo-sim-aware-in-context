"""
Provider router: dispatch chat() to the right backend based on the model id.

Agents import chat() from here. Provider is inferred from the (already
alias-resolved) model string via icpi.config.provider_for:
  - "gemini-*"          → Gemini SDK client
  - "deepseek-*"        → DeepSeek direct (OpenAI-compatible)
  - "vendor/model"      → OpenRouter gateway (open-source & closed models)
"""
from __future__ import annotations

from icpi.config import provider_for


def chat(
    system_prompt: str,
    user_prompt: str,
    output_schema: dict | None = None,
    json_mode: bool = False,
    model: str = "gemini-2.5-flash",
) -> dict | str:
    provider = provider_for(model)
    if provider.name == "gemini":
        from llm_api.gemini_client import chat as _chat
        return _chat(system_prompt, user_prompt, output_schema, json_mode, model)

    from llm_api.openai_compat import chat as _chat
    return _chat(system_prompt, user_prompt, output_schema, json_mode, model, provider)
