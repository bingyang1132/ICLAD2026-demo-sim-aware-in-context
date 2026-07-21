"""
Gemini client — reads API key from key.txt exactly once.
Never logs or prints the key. Records usage in icpi.usage.TRACKER.
"""
from __future__ import annotations
import json
import time
import logging
from pathlib import Path
from typing import Any

import google.genai as genai
from google.genai import types as genai_types

from icpi.config import KEY_FILE, MAX_LLM_RETRIES, LLM_RETRY_DELAY
from icpi.usage import TRACKER

logger = logging.getLogger(__name__)

_client: genai.Client | None = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        key = Path(KEY_FILE).read_text().strip()
        _client = genai.Client(api_key=key)
    return _client


def _extract_usage(response) -> tuple[int, int]:
    """Extract (prompt_tokens, completion_tokens) from a genai response."""
    um = getattr(response, "usage_metadata", None)
    if um is None:
        return 0, 0
    pt = getattr(um, "prompt_token_count", 0) or 0
    ct = getattr(um, "candidates_token_count", 0) or 0
    return pt, ct


def chat(
    system_prompt: str,
    user_prompt: str,
    output_schema: dict | None = None,
    json_mode: bool = False,
    model: str = "gemini-2.5-flash",
) -> dict | str:
    """
    Call Gemini and return parsed JSON (if output_schema or json_mode) or raw text.

    json_mode=True sets response_mime_type=application/json WITHOUT a response_schema.
    This lets the model freely follow prompt instructions rather than schema-constrained
    decoding, which tends to produce minimal-valid JSON (e.g. {} for open object schemas).
    """
    client = _get_client()

    want_json = bool(output_schema) or json_mode
    config_kwargs: dict[str, Any] = {"system_instruction": system_prompt}
    if output_schema:
        config_kwargs["response_mime_type"] = "application/json"
        config_kwargs["response_schema"] = output_schema
    elif json_mode:
        config_kwargs["response_mime_type"] = "application/json"
    generation_config = genai_types.GenerateContentConfig(**config_kwargs)

    delay = LLM_RETRY_DELAY
    last_exc: Exception | None = None
    for attempt in range(MAX_LLM_RETRIES):
        t0 = time.time()
        try:
            response = client.models.generate_content(
                model=model,
                contents=user_prompt,
                config=generation_config,
            )
            duration = time.time() - t0
            pt, ct = _extract_usage(response)
            text = response.text
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
