"""
Generic OpenAI-compatible chat client (httpx, no extra dependency).

Works for any provider exposing the OpenAI /chat/completions API, e.g.:
  - DeepSeek        (https://api.deepseek.com/v1)   — deepseek-chat, deepseek-reasoner
  - OpenRouter      (https://openrouter.ai/api/v1)   — gateway to many open-source models

Mirrors llm_api.gemini_client.chat's signature and TRACKER accounting so the
router can dispatch to either backend transparently.

Never logs or prints the API key.
"""
from __future__ import annotations
import json
import time
import logging
from typing import Any

import httpx

from icpi.config import MAX_LLM_RETRIES, LLM_RETRY_DELAY, Provider
from icpi.usage import TRACKER

logger = logging.getLogger(__name__)

# Cache resolved API keys per provider so we read the key file only once.
_KEY_CACHE: dict[str, str] = {}

# OpenAI-compatible APIs have no Gemini-style response_schema. When the caller
# passes an output_schema we fall back to JSON mode and inject the schema into
# the system prompt so the model still knows the exact required shape.
_SCHEMA_INSTRUCTION = (
    "\n\nYou MUST reply with a single JSON object that strictly conforms to this "
    "JSON Schema (no markdown fences, no prose):\n{schema}"
)


def _get_key(provider: Provider) -> str:
    if provider.name not in _KEY_CACHE:
        _KEY_CACHE[provider.name] = provider.read_key()
    return _KEY_CACHE[provider.name]


def _extract_usage(data: dict) -> tuple[int, int]:
    """Extract (prompt_tokens, completion_tokens) from an OpenAI response body."""
    um = data.get("usage") or {}
    return int(um.get("prompt_tokens", 0) or 0), int(um.get("completion_tokens", 0) or 0)


def chat(
    system_prompt: str,
    user_prompt: str,
    output_schema: dict | None = None,
    json_mode: bool = False,
    model: str = "deepseek-chat",
    provider: Provider | None = None,
) -> dict | str:
    """
    Call an OpenAI-compatible endpoint and return parsed JSON (when output_schema
    or json_mode) or raw text. `provider` carries base_url + auth for the backend.
    """
    if provider is None:
        raise ValueError("openai_compat.chat requires a provider")

    want_json = bool(output_schema) or json_mode
    system = system_prompt
    if output_schema:
        system = system + _SCHEMA_INSTRUCTION.format(schema=json.dumps(output_schema))

    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_prompt},
        ],
    }
    if want_json:
        payload["response_format"] = {"type": "json_object"}

    headers = {
        "Authorization": f"Bearer {_get_key(provider)}",
        "Content-Type": "application/json",
    }
    url = provider.base_url.rstrip("/") + "/chat/completions"

    delay = LLM_RETRY_DELAY
    last_exc: Exception | None = None
    for attempt in range(MAX_LLM_RETRIES):
        t0 = time.time()
        try:
            resp = httpx.post(url, headers=headers, json=payload, timeout=120.0)
            resp.raise_for_status()
            data = resp.json()
            duration = time.time() - t0
            pt, ct = _extract_usage(data)
            text = data["choices"][0]["message"]["content"]
            if want_json:
                parsed = json.loads(text)
                TRACKER.record_call(pt, ct, duration, model, success=True)
                return parsed
            TRACKER.record_call(pt, ct, duration, model, success=True)
            return text
        except json.JSONDecodeError as e:
            duration = time.time() - t0
            TRACKER.record_call(0, 0, duration, model, success=False)
            logger.warning("JSON parse failed (attempt %d): %s", attempt + 1, e)
            last_exc = e
        except Exception as e:
            duration = time.time() - t0
            TRACKER.record_call(0, 0, duration, model, success=False)
            logger.warning("LLM call failed (attempt %d): %s", attempt + 1, e)
            last_exc = e
        if attempt < MAX_LLM_RETRIES - 1:
            time.sleep(delay)
            delay *= 2

    raise RuntimeError(f"LLM call failed after {MAX_LLM_RETRIES} attempts") from last_exc
